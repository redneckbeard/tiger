import time
from datetime import datetime, date
from decimal import Decimal

from django.core.urlresolvers import reverse
from django.contrib.auth.models import User
from django.contrib.localflavor.us.models import PhoneNumberField
from django.db import models
from django.db.models.signals import post_save
from django.template.defaultfilters import slugify
from django.utils.http import int_to_base36
from django.utils.safestring import mark_safe

from imagekit.models import ImageModel
from tiger.accounts.models import Site
from tiger.content.handlers import pdf_caching_handler
from tiger.notify.handlers import item_social_handler
from tiger.utils.fields import PickledObjectField


class Section(models.Model):
    """Acts as a container for menu items. Example: "Burritos".
    """
    name = models.CharField(max_length=50)
    site = models.ForeignKey(Site, editable=False)
    description = models.TextField()
    slug = models.SlugField(editable=False)
    ordering = models.PositiveIntegerField(editable=False, default=1)

    class Meta:
        verbose_name = 'menu section'
        ordering = ('ordering',)

    def __unicode__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        if not self.id:
            self.ordering = 1
        super(Section, self).save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('menu_section', kwargs={'section': self.slug})

    def has_specials(self):
        return any(item.special for item in self.item_set.all())


class ItemManager(models.Manager):
    use_for_related_fields = True

    def render_specials_to_string(self, site, template='core/specials_fax.html'):
        items = self.filter(special=True, site=site)
        return render_to_string(template, {'site': site, 'items': items})

    def active(self):
        return self.filter(archived=False)


class Item(models.Model):
    """Represents a single item on the menu in its most basic form.
    """
    name = models.CharField(max_length=100)
    section = models.ForeignKey(Section)
    site = models.ForeignKey(Site, editable=False)
    image = models.ForeignKey('content.ItemImage', blank=True, null=True)
    description = models.TextField(blank=True)
    special = models.BooleanField('is this menu item currently a special?')
    slug = models.SlugField(editable=False)
    ordering = models.PositiveIntegerField(editable=False, default=1)
    spicy = models.BooleanField(default=False)
    vegetarian = models.BooleanField(default=False)
    archived = models.BooleanField(default=False)
    out_of_stock = models.BooleanField(default=False)
    objects = ItemManager()

    class Meta:
        verbose_name = 'menu item'
        ordering = ('ordering',)

    def __unicode__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.id:
            self.slug = slugify(self.name)
        super(Item, self).save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('menu_item', 
            kwargs={'section': self.section.slug, 'item': self.slug})

    def get_short_url(self):
        return reverse('short_code', kwargs={'item_id': int_to_base36(self.id)})

    @property
    def price_list(self):
        if self.variant_set.count() == 1:
            return ['$%.2f' % self.variant_set.all()[0].price]  
        return [
            '%s: $%.2f' % (v.description, v.price)
            for v in self.variant_set.all()
        ]

    @property
    def available(self):
        return not (self.archived or self.out_of_stock)
            


class Variant(models.Model):
    """Represents "column-level" extra data about a menu item.  This means
    information like "Extra large" and the corresponding price.  This is what a
    customer will actually be selecting when ordering a menu item.  All menu
    items must have at least one.  
    """
    item = models.ForeignKey(Item)
    description = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        ordering = ['price']

    def __unicode__(self):
        s = '%s ($<span>%s</span>)' % (self.description, self.price)
        return mark_safe(s)

    def save(self, *args, **kwargs):
        self.price = self.price.quantize(Decimal('0.01'))
        super(Variant, self).save(*args, **kwargs)


class Upgrade(models.Model):
    """Provides additional cost data and/or order processing instructions. For
    example, "Subsitute seasoned frieds for $.50" or "Add extra cheese for
    $1.00." 
    """
    item = models.ForeignKey(Item)
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=5, decimal_places=2)
    substitute = models.BooleanField('Check here for the display text \
        for this item to say "Substitute" instead of "Add"')

    class Meta:
        verbose_name = 'upgrade/substitution'
        verbose_name_plural = 'upgrades/substitutions'

    def __unicode__(self):
        s = '%s %s for $<span>%.02f</span> more' % (
            'Substitute' if self.substitute else 'Add', 
            self.name, self.price)
        return mark_safe(s)

    def save(self, *args, **kwargs):
        self.price = '%.2f' % self.price
        super(Variant, self).save(*args, **kwargs)


class Order(models.Model):
    METHOD_TAKEOUT = 1
    METHOD_DINEIN = 2
    METHOD_CHOICES = (
        (METHOD_TAKEOUT, 'Takeout'),
        (METHOD_DINEIN, 'Dine in'),
    )
    site = models.ForeignKey(Site, null=True, editable=False)
    name = models.CharField(max_length=50)
    phone = PhoneNumberField()
    pickup = models.DateTimeField()
    total = models.DecimalField(editable=False, max_digits=6, decimal_places=2)
    cart = PickledObjectField(editable=False)
    timestamp = models.DateTimeField(default=datetime.now, editable=False)
    method = models.IntegerField(default=1, choices=METHOD_CHOICES)

    @models.permalink
    def get_absolute_url(self):
        return 'order_detail', [self.id], {}


class Coupon(models.Model):
    site = models.ForeignKey(Site, editable=False)
    short_code = models.CharField(max_length=20, help_text='Uppercase letters and numbers only. Leave this blank to have a randomly generated coupon code.')
    exp_date = models.DateField('Expiration date', null=True, blank=True)
    click_count = models.IntegerField('Number of uses', editable=False, default=0)
    max_clicks = models.IntegerField('Max. allowed uses', null=True, blank=True)
    discount = models.IntegerField()

    def save(self, *args, **kwargs):
        if not self.id and not self.short_code:
            self.short_code = int_to_base36(int(time.time())).upper()
        super(Coupon, self).save(*args, **kwargs)

    def log_use(self, order):
        if self.max_clicks:
            self.click_count += 1
        self.save()
        CouponUse.objects.create(order=order, coupon=self)

    @property
    def is_open(self):
        date_is_valid = self.exp_date is None or self.exp_date <= date.today()
        has_clicks_available = self.max_clicks is None or self.click_count < self.max_clicks
        if not (date_is_valid and has_clicks_available):
            return False
        return True


class CouponUse(models.Model):
    coupon = models.ForeignKey(Coupon)
    order = models.ForeignKey(Order)
    timestamp = models.DateTimeField(default=datetime.now)


post_save.connect(item_social_handler, sender=Item)
post_save.connect(pdf_caching_handler, sender=Item)
