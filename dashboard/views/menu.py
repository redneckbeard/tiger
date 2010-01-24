from django.core.urlresolvers import reverse
from django.forms.models import inlineformset_factory
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render_to_response
from django.views.generic.simple import direct_to_template

from tiger.core.forms import *
from tiger.core.models import *
from tiger.utils.forms import RequireOneFormSet

def _reorder_objects(model, id_list):
    for i, obj_id in enumerate(id_list):
        obj = model.objects.get(id=obj_id)
        obj.ordering = i + 1
        obj.save()

def dashboard(request):
    site = request.site
    specials = site.item_set.filter(special=True)
    updates = site.scheduledupdate_set.all() 
    return direct_to_template(request, template='dashboard.html', extra_context={
        'specials': specials,
        'updates': updates
    })

def section_list(request):
    site = request.site
    return direct_to_template(request, template='dashboard/section_list.html', extra_context={
        'sections': site.section_set.all()
    })

def add_edit_section(request, section_id=None):
    instance = None
    site = request.site
    if section_id is not None:
        instance = Section.objects.get(id=section_id)
        if instance.site != site:
            raise Http404()
    if request.method == 'POST':
        form = SectionForm(request.POST, instance=instance)
        if form.is_valid():
            section = form.save(commit=False)
            section.site = site
            section.save()
            return HttpResponseRedirect(reverse('dashboard_menu'))
    else:
        form = SectionForm(instance=instance)
    return direct_to_template(request, template='dashboard/section_form.html', extra_context={
        'form': form
    })


def delete_section(request, section_id):
    site = request.site
    instance = Section.objects.get(id=section_id)
    if instance.site != site:
        raise Http404()
    instance.delete()
    return HttpResponseRedirect(reverse('dashboard_menu'))


def view_section(request, section_id):
    site = request.site
    instance = Section.objects.get(id=section_id)
    if instance.site != site:
        raise Http404()
    return render_to_response('dashboard/includes/item_list.html', {'items': instance.item_set.all()})

def reorder_sections(request):
    section_ids = request.POST.getlist('section_ids')
    _reorder_objects(Section, section_ids)
    return HttpResponse('')

def add_edit_item(request, item_id=None):
    instance = None
    site = request.site
    if item_id is not None:
        instance = Item.objects.get(id=item_id)
        if instance.site != site:
            raise Http404()
    ItemForm = get_item_form(site)
    VariantFormSet = inlineformset_factory(Item, Variant, formset=RequireOneFormSet, extra=1)
    UpgradeFormSet = inlineformset_factory(Item, Upgrade, extra=1)
    if request.method == 'POST':
        form = ItemForm(request.POST, instance=instance)
        variant_formset = VariantFormSet(request.POST, instance=instance, prefix='variants')
        upgrade_formset = UpgradeFormSet(request.POST, instance=instance, prefix='upgrades')
        if all([form.is_valid(), variant_formset.is_valid(), upgrade_formset.is_valid()]):
            item = form.save(commit=False)
            item.site = site
            item.save()
            if instance is not None:
                variant_formset.save()
                upgrade_formset.save()
            else:
                for form in variant_formset.forms:
                    variant = form.save(commit=False)
                    variant.item = item
                    variant.save()
                for form in upgrade_formset.forms:
                    upgrade = form.save(commit=False)
                    upgrade.item = item
                    upgrade.save()
            return HttpResponseRedirect(reverse('dashboard_menu'))
    else:
        form_kwds = {}
        if instance is not None:
            form_kwds['instance'] = instance 
        elif request.GET.get('pk'):
            form_kwds['initial'] = {'section': request.GET['pk']}
        form = ItemForm(**form_kwds)
        variant_formset = VariantFormSet(instance=instance, prefix='variants')
        upgrade_formset = UpgradeFormSet(instance=instance, prefix='upgrades')
    return direct_to_template(request, template='dashboard/item_form.html', extra_context={
        'form': form, 'variant_formset': variant_formset, 'upgrade_formset': upgrade_formset
    })

def delete_item(request, item_id):
    site = request.site
    instance = Item.objects.get(id=item_id)
    if instance.site != site:
        raise Http404()
    instance.delete()
    return HttpResponseRedirect(reverse('dashboard_menu'))

def reorder_items(request):
    item_ids = request.POST.getlist('item_ids')
    _reorder_objects(Item, item_ids)
    return HttpResponse('')

