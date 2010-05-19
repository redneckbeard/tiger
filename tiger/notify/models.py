from datetime import datetime

from django.core.cache import cache
from django.db import models
from django.db.models.signals import post_save
from django.template.defaultfilters import slugify
from django.template.loader import render_to_string

from greatape import MailChimp
from markdown import markdown

from tiger.content.models import PdfMenu
from tiger.notify.fax import FaxMachine
from tiger.utils.pdf import render_to_pdf


class Fax(models.Model):
    DIRECTION_INBOUND = 1
    DIRECTION_OUTBOUND = 2
    DIRECTION_CHOICES = (
        (DIRECTION_INBOUND, 'Inbound'),
        (DIRECTION_OUTBOUND, 'Outbound'),
    )
    site = models.ForeignKey('accounts.Site')
    timestamp = models.DateTimeField(null=True, blank=True)
    page_count = models.IntegerField(null=True, blank=True)
    parent_transaction = models.CharField(max_length=100, null=True)
    transaction = models.CharField(max_length=100)
    completion_time = models.DateTimeField(null=True, blank=True)
    destination = models.CharField(max_length=20, null=True, blank=True)


class Social(models.Model):
    CAMPAIGN_NO_CREATE = 0
    CAMPAIGN_CREATE = 1
    CAMPAIGN_SEND = 2
    CAMPAIGN_CHOICES = (
        (CAMPAIGN_NO_CREATE, 'Do not create campaigns for blasts'),
        (CAMPAIGN_CREATE, 'Create campaigns for blasts that can be sent from MailChimp'),
        (CAMPAIGN_SEND, 'Create and automatically send campaigns for blasts'),
    )
    site = models.OneToOneField('accounts.Site')
    twitter_screen_name = models.CharField(max_length=20, blank=True)
    twitter_token = models.CharField(max_length=255, blank=True)
    twitter_secret = models.CharField(max_length=255, blank=True)
    facebook_id = models.CharField(max_length=20, blank=True, null=True)
    facebook_url = models.TextField(blank=True, null=True)
    mailchimp_api_key = models.CharField(max_length=100, null=True, blank=True)
    mailchimp_list_id = models.CharField(max_length=50, null=True, blank=True)
    mailchimp_list_name = models.CharField(max_length=100, null=True, blank=True)
    mailchimp_allow_signup = models.BooleanField('Provide a signup box on your web site', default=False)
    mailchimp_send_blast = models.IntegerField(
        default=CAMPAIGN_NO_CREATE, choices=CAMPAIGN_CHOICES)

    @property
    def mailchimp_lists(self):
        CACHE_KEY = 'mailchimp_choices-%d' % self.id
        mailchimp_choices = cache.get(CACHE_KEY)
        if mailchimp_choices is None:
            mailchimp = MailChimp(self.mailchimp_api_key)
            mailchimp_choices = [
                (lst['id'], lst['name'])
                for lst in mailchimp.lists()
            ]
            cache.set(CACHE_KEY, mailchimp_choices, 3600)
        return mailchimp_choices


class Release(models.Model):
    site = models.ForeignKey('accounts.Site')
    title = models.CharField(max_length=140)
    slug = models.SlugField(editable=False)
    body = models.TextField(blank=True)
    body_html = models.TextField(blank=True, editable=False)
    pdf = models.ForeignKey(PdfMenu, verbose_name='Select one of your PDF menus', null=True, blank=True)
    coupon = models.ForeignKey('core.Coupon', null=True, blank=True)
    time_sent = models.DateTimeField(editable=False)
    fax_transaction = models.CharField(null=True, blank=True, max_length=100, editable=False)

    def __unicode__(self):
        return self.title

    def save(self, *args, **kwargs):
        from tiger.notify.tasks import PublishTask
        self.body_html = markdown(self.body)
        self.slug = slugify(self.title)
        if not self.id:
            self.time_sent = datetime.now()
        super(Release, self).save(*args, **kwargs)
        PublishTask.delay(self.id)

    @models.permalink
    def get_absolute_url(self):
        return 'press_detail', (), {'object_id': self.id, 'slug': self.slug}

    def get_body_html(self):
        return render_to_string('notify/release_mail.html', {'release': self})

    def get_body_text(self):
        return render_to_string('notify/release_mail.txt', {'release': self})

    def send_mailchimp(self):
        site = self.site
        social = site.social
        if social.mailchimp_send_blast != Social.CAMPAIGN_NO_CREATE:
            mailchimp = MailChimp(social.mailchimp_api_key)
            campaign_id = mailchimp.campaignCreate(
                type='regular',
                options={
                    'list_id': social.mailchimp_list_id,
                    'subject': self.title,
                    'from_email': site.email,
                    'from_name': site.name,
                    'to_name': '%s subscribers' % site.name,
                },
                content={
                    'html': self.get_body_html(),
                    'text': self.get_body_text()
            })
            if social.mailchimp_send_blast == Social.CAMPAIGN_SEND:
                mailchimp.campaignSendNow(cid=campaign_id)
                
    def send_fax(self, fax_list):
        site = self.site
        social = site.social
        fax_machine = FaxMachine(site)
        content = open(self.pdf.path).read()
        kwargs ={}
        if self.body:
            cover_page = render_to_pdf('notify/cover_page.html', {'release': self})
            kwargs['FileSizes'] = '%d;%d' % (len(cover_page), len(content))
            kwargs['FileTypes'] = 'PDF;PDF'
            content = cover_page + content
        fax_numbers = [s.fax for s in fax_list.subscriber_set.all()]
        transaction = fax_machine.send(fax_numbers, content, **kwargs)
        self.fax_transaction = transaction
        self.save()
        Fax.objects.create(parent_transaction=transaction, 
            transaction=transaction, site=site)

def new_site_setup(sender, instance, created, **kwargs):
    if created:
        Site = models.get_model('accounts', 'site')
        if isinstance(instance, Site):
            Social.objects.create(site=instance)


post_save.connect(new_site_setup)
