from datetime import datetime, date
import random

from django.conf import settings
from django.contrib.localflavor.us.models import *
from django.db import models, connection
from django.utils import simplejson as json
from django.utils.dateformat import format

from pytz import timezone

import twilio

from tiger.utils.models import Message
from tiger.sms.sender import Sender

# Create your models here.

class SmsSettings(models.Model):
    sms_number = PhoneNumberField(null=True)
    sid = models.CharField(max_length=34, null=True)
    send_intro = models.BooleanField('send an automated introductory SMS when someone first subscribes', default=False, blank=True)
    intro_sms = models.CharField(max_length=160, null=True)

    @property
    def enabled(self):
        return bool(self.sms_number)

    def get_options_for(self, attr):
        cursor = connection.cursor()
        cursor.execute("""SELECT DISTINCT sub.%s FROM sms_smssubscriber sub
        INNER JOIN sms_smssettings set ON sub.settings_id = set.id
        WHERE set.id = %%s AND sub.unsubscribed_at IS NULL
        """ % attr, [self.id])
        return json.dumps([r[0] for r in cursor.fetchall() if r[0]])


class SmsSubscriberManager(models.Manager):
    use_for_related_fields = True

    def active(self):
        return self.filter(unsubscribed_at__isnull=True)

    def inactive(self):
        return self.filter(unsubscribed_at__isnull=False)


class SmsSubscriber(models.Model):
    settings = models.ForeignKey(SmsSettings)
    phone_number = PhoneNumberField(null=True, blank=True)
    city = models.CharField(max_length=100, null=True)
    state = USStateField(null=True)
    zip_code = models.CharField(max_length=10, null=True)
    menus_first = models.BooleanField(default=False)
    signed_up_at = models.DateTimeField()
    unsubscribed_at = models.DateTimeField(null=True)
    starred = models.BooleanField(default=False)
    objects = SmsSubscriberManager()

    def save(self, *args, **kwargs):
        new = not self.id
        if new:
            self.signed_up_at = datetime.now()
        super(SmsSubscriber, self).save(*args, **kwargs)
        if new and self.settings.send_intro:
            self.send_message(self.settings.intro_sms)

    @property
    def is_active(self):
        return not self.unsubscribed_at

    def send_message(self, body, sms_number=None, campaign=None):
        sender = self.sender(self.settings, body)
        sender.add_recipients(self)
        sender.send_message()

    def sender(self, settings, body):
        return Sender(settings, body)


class Campaign(models.Model):
    settings = models.ForeignKey(SmsSettings, editable=False)
    title = models.CharField('title (for your reference later)', max_length=255)
    body = models.CharField(max_length=160)
    timestamp = models.DateTimeField(editable=False, auto_now_add=True)
    filter_on = models.CharField(max_length=100, blank=True, choices=[
        ('city', 'city'),
        ('state', 'state'),
        ('zip_code', 'zip code')
    ])
    filter_value = models.CharField(max_length=100, blank=True)
    starred = models.NullBooleanField(default=None)
    count = models.PositiveIntegerField('max. number of SMSes to send')
    sent_count = models.PositiveIntegerField(default=0, editable=False)
    subscribers = models.ManyToManyField(SmsSubscriber, editable=False)
    completed = models.BooleanField(default=False, editable=False)

    def set_subscribers(self):
        subscribers = self.settings.smssubscriber_set.active()
        if self.filter_on and self.filter_value:
            subscribers = subscribers.filter(**{self.filter_on: self.filter_value})
        if self.starred is not None:
            subscribers = subscribers.filter(starred=self.starred)
        subscribers = list(subscribers)
        self.count = len(subscribers)
        self.save()
        random.shuffle(subscribers)
        self.subscribers.add(*subscribers[:self.count])

    def queue(self):
        #TODO: provide callback URL
        from tiger.sms.tasks import SmsBroadcastTask
        SmsBroadcastTask.delay(self.id)

    def broadcast(self):
        sender = Sender(self.settings.site_set.all()[0], self.body, campaign=self)
        sender.add_recipients(*list(self.subscribers.all()))
        sender.send_message()
        self.completed = True
        self.save()

    def img_url(self):
        urls = {
            None: 'both_stars.png',
            False: 'unstarred.png',
            True: 'Favourite_24x24.png',
        }
        return urls[self.starred]
            

class SmsManager(models.Manager):
    def inbox_for(self, settings):
        return Thread.objects.filter(settings=settings)

    def thread_for(self, settings, phone_number):
        return self.filter(
            settings=settings, 
            phone_number=phone_number, 
            conversation=True
        ).order_by('timestamp')


class SMS(Message):
    DELIVERY_PENDING = 0
    DELIVERY_SUCCESS = 1
    DELIVERY_FAILURE = 2
    settings = models.ForeignKey(SmsSettings)
    campaign = models.ForeignKey(Campaign, null=True)
    subscriber = models.ForeignKey(SmsSubscriber, null=True)
    sid = models.CharField(max_length=34)
    body = models.CharField(max_length=160)
    status = models.IntegerField(default=DELIVERY_PENDING)
    conversation = models.BooleanField(default=False)
    phone_number = models.CharField(max_length=20)
    objects = SmsManager()

    def save(self, *args, **kwargs):
        super(SMS, self).save(*args, **kwargs)
        if self.body.strip().lower() == 'out':
            subscriber = self.subscriber
            subscriber.unsubscribed_at = datetime.now()
            subscriber.save()
        if self.conversation:
            try:
                thread = Thread.objects.get(phone_number=self.phone_number)
            except Thread.DoesNotExist:
                if self.destination == SMS.DIRECTION_OUTBOUND:
                    return
                thread = Thread.objects.create(
                    settings=self.settings,
                    phone_number=self.phone_number,
                    timestamp=self.timestamp,
                    body=self.body
                )
            else:
                to_update = {
                    'body': self.body,
                    'message_count': SMS.objects.thread_for(settings=self.settings, phone_number=self.phone_number).count()
                }
                if self.destination == SMS.DIRECTION_INBOUND:
                    to_update['unread'] = True
                    to_update['timestamp'] = self.timestamp
                Thread.objects.filter(phone_number=self.phone_number).update(**to_update)

    def get_timestamp(self):
        timestamp = self.timestamp
        if timestamp.date() == date.today():
            format_string = 'P'
        elif timestamp.year == date.today().year:
            format_string = 'n/j/y'
        else:
            format_string = 'M j'
        return format(timestamp, format_string)


class Thread(models.Model):
    settings = models.ForeignKey(SmsSettings)
    phone_number = models.CharField(max_length=20)
    body = models.CharField(max_length=160)
    unread = models.BooleanField(default=True)
    timestamp = models.DateTimeField()
    message_count = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ('-timestamp',)

    def get_timestamp(self):
        timestamp = self.timestamp
        if timestamp.date() == date.today():
            format_string = 'P'
        elif timestamp.year == date.today().year:
            format_string = 'n/j/y'
        else:
            format_string = 'M j'
        return format(timestamp, format_string)