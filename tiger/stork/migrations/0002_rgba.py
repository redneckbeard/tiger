# encoding: utf-8
import datetime
from south.db import db
from south.v2 import DataMigration
from django.db import models

class Migration(DataMigration):
    def forwards(self, orm):
        for swatch in orm.Swatch.objects.all():
            color = swatch.color
            rgb = [int(n + m, 16) for n, m in zip(color[::2], color[1::2])]
            swatch.color = ','.join(str(channel) for channel in rgb)
            swatch.save()

    def backwards(self, orm):
        for swatch in orm.Swatch.objects.all():
            color = swatch.color
            hex_style = [hex(int(n))[2:] for n, m in zip(color[::2], color[1::2])]
            swatch.color = ''.join(hex_style)
            swatch.save()

    models = {
        'stork.css': {
            'Meta': {'object_name': 'CSS'},
            'component': ('django.db.models.fields.CharField', [], {'max_length': '50'}),
            'css': ('django.db.models.fields.TextField', [], {}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'theme': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['stork.Theme']"})
        },
        'stork.font': {
            'Meta': {'object_name': 'Font'},
            'component': ('django.db.models.fields.CharField', [], {'max_length': '50'}),
            'font': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['stork.FontStack']"}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'theme': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['stork.Theme']"})
        },
        'stork.fontstack': {
            'Meta': {'object_name': 'FontStack'},
            'eot': ('django.db.models.fields.files.FileField', [], {'max_length': '100', 'null': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '20'}),
            'stack': ('django.db.models.fields.TextField', [], {'max_length': '255'}),
            'svg': ('django.db.models.fields.files.FileField', [], {'max_length': '100', 'null': 'True'}),
            'ttf': ('django.db.models.fields.files.FileField', [], {'max_length': '100', 'null': 'True'}),
            'woff': ('django.db.models.fields.files.FileField', [], {'max_length': '100', 'null': 'True'})
        },
        'stork.html': {
            'Meta': {'object_name': 'Html'},
            'component': ('django.db.models.fields.CharField', [], {'max_length': '50'}),
            'html': ('django.db.models.fields.TextField', [], {}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'invalid_html': ('django.db.models.fields.TextField', [], {'null': 'True', 'blank': 'True'}),
            'staged_html': ('django.db.models.fields.TextField', [], {}),
            'theme': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['stork.Theme']"})
        },
        'stork.image': {
            'Meta': {'object_name': 'Image'},
            'component': ('django.db.models.fields.CharField', [], {'max_length': '50'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'image': ('django.db.models.fields.files.ImageField', [], {'max_length': '100', 'null': 'True', 'blank': 'True'}),
            'staged_image': ('django.db.models.fields.files.ImageField', [], {'max_length': '100', 'null': 'True', 'blank': 'True'}),
            'theme': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['stork.Theme']"}),
            'tiling': ('django.db.models.fields.BooleanField', [], {'default': 'False'})
        },
        'stork.swatch': {
            'Meta': {'object_name': 'Swatch'},
            'color': ('django.db.models.fields.CharField', [], {'max_length': '6'}),
            'component': ('django.db.models.fields.CharField', [], {'max_length': '50'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'theme': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['stork.Theme']"})
        },
        'stork.theme': {
            'Meta': {'object_name': 'Theme'},
            'bundled_css': ('django.db.models.fields.files.FileField', [], {'max_length': '100', 'null': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'private': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'saved_at': ('django.db.models.fields.DateTimeField', [], {'auto_now': 'True', 'blank': 'True'})
        }
    }

    complete_apps = ['stork']