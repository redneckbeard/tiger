from decimal import InvalidOperation

from django.contrib import messages
from django.core.urlresolvers import reverse
from django.core.validators import email_re
from django.forms.util import ErrorList
from django.http import HttpResponsePermanentRedirect, HttpResponseRedirect, Http404
from django.shortcuts import get_object_or_404

from greatape import MailChimp, MailChimpError
from paypal.standard.forms import PayPalPaymentsForm

from tiger.core.exceptions import OrderingError
from tiger.core.forms import get_order_form, OrderForm, CouponForm, AuthNetForm
from tiger.core.models import Section, Item, Coupon, Order
from tiger.notify.tasks import DeliverOrderTask
from tiger.utils.views import render_custom

def section_list(request):
    sections = Section.objects.filter(site=request.site)
    return render_custom(request, 'core/section_list.html', 
        {'sections': sections})

def section_detail_abbr(request, section):
    try:
        s = Section.objects.filter(slug=section, site=request.site)[0]
    except:
        raise Http404
    return HttpResponsePermanentRedirect(s.get_absolute_url())
    
def section_detail(request, section_id, section_slug):
    s = get_object_or_404(Section, slug=section_slug, id=section_id, site=request.site)
    return render_custom(request, 'core/section_detail.html', 
        {'section': s})
    
def item_detail_abbr(request, section, item):
    try:
        i = Item.objects.filter(section__slug=section, slug=item, site=request.site)[0]
    except:
        raise Http404
    return HttpResponsePermanentRedirect(i.get_absolute_url())

def item_detail(request, section_id, section_slug, item_id, item_slug):
    i = get_object_or_404(Item, section__slug=section_slug, section__id=section_id, id=item_id, slug=item_slug, site=request.site)
    try:
        assert i.is_available
    except OrderingError, e:
        messages.warning(request, e.msg) 
    if i.price_list in (None, []):
        if request.user.is_authenticated() and request.site.account.user == request.user:
            messages.warning(request, 'This is menu item is incomplete and will not appear to users.  To complete it, <a href="%s">add a price</a>.' % reverse('dashboard_edit_options', args=['item', i.id]))
        else:
            raise Http404
    return render_custom(request, 'core/item_detail.html', 
        {'item': i, 'sections': request.site.section_set.all()})

def order_item(request, section_id, section_slug, item_id, item_slug):
    i = get_object_or_404(Item, section__slug=section_slug, section__id=section_id, id=item_id, slug=item_slug, site=request.site)
    try:
        assert request.site.is_open and i.is_available
    except OrderingError, e:
        messages.warning(request, e.msg) 
        return HttpResponseRedirect(e.redirect_to)
    OrderForm = get_order_form(i)
    total = i.variant_set.order_by('-price')[0].price
    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            request.cart.add(i, form)
            msg = """%s added to your order. You can 
            <a href="%s">complete your order now</a> or <a href="/menu/">add more items</a>.""" % (
                i.name, reverse('preview_order'))
            messages.success(request, msg) 
            return HttpResponseRedirect(i.section.get_absolute_url())
    else:
        form = OrderForm()
    return render_custom(request, 'core/order_form.html', {'item': i, 'form': form, 'total': '%.2f' % total, 'sections': request.site.section_set.all()})

def preview_order(request):
    if not hasattr(request, 'cart'):
        return HttpResponseRedirect('/menu/')
    if request.method == 'POST':
        form = CouponForm(request.site, request.POST)
        if request.cart.has_coupon:
            messages.error(request, 'You have already added a coupon to this order.')   
        elif form.is_valid():
            coupon = form.coupon
            request.cart.add_coupon(coupon)
            return HttpResponseRedirect(reverse('preview_order'))
    else:
        if request.cart.has_coupon:
            form = None
        else:
            form = CouponForm()
    return render_custom(request, 'core/preview_order.html', 
        {'form': form})

def remove_item(request):
    request.cart.remove(request.GET.get('id'))
    return HttpResponseRedirect(reverse('preview_order'))

def add_coupon(request):
    code = request.GET.get('cc')
    if code is None:
        raise Http404
    coupon = get_object_or_404(Coupon, id=code, site=request.site)
    if not hasattr(request, 'cart'):
        return HttpResponseRedirect('?'.join([reverse('add_coupon'), request.META['QUERY_STRING']]))
    if request.cart.has_coupon:
        messages.error(request, 'You already have a coupon in your cart.')   
    else:
        request.cart.add_coupon(coupon)
        messages.success(request, 'Coupon added to your cart successfully.')   
    return HttpResponseRedirect(reverse('menu_home'))

def clear_coupon(request):
    request.cart.remove_coupon()
    messages.success(request, 'Your coupon has been removed.')   
    return HttpResponseRedirect(reverse('preview_order'))

def send_order(request):
    try:
        assert request.site.is_open
    except OrderingError, e:
        messages.warning(request, e.msg)
        return HttpResponseRedirect(e.redirect_to)
    # cart sanity checks:
    # if cart is empty, redirect with message
    if not len(request.cart):
        messages.warning(request, "Your order is empty.  Please add your desired menu items and try again.")
        return HttpResponseRedirect(reverse('menu_home'))
    # if they have an incomplete order, fetch it
    cart_key = request.cart.session.session_key
    try:
        instance = Order.objects.get(session_key=cart_key, status=Order.STATUS_INCOMPLETE)
    except:
        instance = None
    if request.method == 'POST':
        form = OrderForm(request.POST, site=request.site, instance=instance)
        form.total = request.cart.total()
        if form.is_valid():
            order = form.save(commit=False)
            order.total = request.cart.total()
            order.tax = request.cart.taxes()
            cart = request.cart.session.get_decoded()
            order.cart = cart
            order.session_key = cart_key
            order.site = request.site
            try:
                order.save()
            except InvalidOperation:
                form._errors['__all__'] = ErrorList(['Your order is too large.  Please contact us for catering options.'])
            else:
                if request.cart.has_coupon:
                    coupon = Coupon.objects.get(id=request.cart['coupon']['id'])
                    coupon.log_use(order, request.cart.discount())
                if 'pay' in request.POST:
                    request.session['order_id'] = order.id
                    return HttpResponseRedirect(
                        request.site.ordersettings.payment_url(
                            cart_id=request.cart.session.session_key,
                            order_id=order.id
                        )
                    )
                DeliverOrderTask.delay(order.id, Order.STATUS_SENT)
                return HttpResponseRedirect(reverse('order_success'))
    else:
        form = OrderForm(site=request.site)
    context = {
        'form': form
    }
    return render_custom(request, 'core/send_order.html', context)

def payment_paypal(request):
    try:
        order = Order.objects.get(id=request.session['order_id'])
    except (Order.DoesNotExist, KeyError):
        return HttpResponseRedirect(reverse('preview_order'))
    site = request.site
    domain = str(site)
    paypal_dict = {
        'business': site.ordersettings.paypal_email,
        'amount': order.total_plus_tax(),
        'invoice': request.session['order_id'],
        'item_name': 'Your order at %s' % site.name,
        'notify_url': domain + reverse('paypal-ipn'),
        'return_url': domain + reverse('order_success'),
        'cancel_return': domain + reverse('preview_order'),
    }
    form = PayPalPaymentsForm(initial=paypal_dict)
    context = {'form': form}
    return render_custom(request, 'core/payment_paypal.html', context)

def payment_authnet(request):
    order_id = request.REQUEST.get('o')
    try:
        order = Order.objects.get(id=order_id)
    except (Order.DoesNotExist, KeyError):
        return HttpResponseRedirect(reverse('preview_order'))
    if request.method == 'POST':
        form = AuthNetForm(request.POST, order=order)
        if form.is_valid():
            order.notify_restaurant(Order.STATUS_PAID)
            return HttpResponseRedirect(str(request.site) + reverse('order_success'))
    else:
        form = AuthNetForm(order=order)
    context = {'form': form, 'order_id': order_id, 'order_settings': request.site.ordersettings}
    return render_custom(request, 'core/payment_authnet.html', context)
            

def order_success(request):
    return render_custom(request, 'core/order_success.html')

def mailing_list_signup(request):
    email = request.POST.get('email', '')
    if email_re.match(email):
        social = request.site.social
        mailchimp = MailChimp(social.mailchimp_api_key)
        try:
            response = mailchimp.listSubscribe(
                id=social.mailchimp_list_id, 
                email_address=email,
                merge_vars=''
            )
        except MailChimpError, e:
            if e.code == 214:
                messages.success(request, 'You are already on our mailing list.  Thanks for your continued interest!')
        else:
            if response is True:
                success_msg = 'Thanks for signing up!  We\'ll send you a confirmation e-mail shortly.'
                messages.success(request, success_msg)
            else:
                messages.warning(request, 'We were unable to sign you up at this time.  Please try again.')
    else:
        error_msg = 'Please enter a valid e-mail address.'
        messages.error(request, error_msg)
    return HttpResponseRedirect(request.META['HTTP_REFERER'])
