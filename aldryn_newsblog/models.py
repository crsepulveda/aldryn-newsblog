# -*- coding: utf-8 -*-

from __future__ import unicode_literals

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.urlresolvers import reverse
from django.db import IntegrityError, models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.text import slugify as default_slugify
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.models import User

from cms.models.fields import PlaceholderField
from cms.models.pluginmodel import CMSPlugin
from aldryn_people.models import Person
from filer.fields.image import FilerImageField
from parler.models import TranslatableModel, TranslatedFields
from aldryn_apphooks_config.models import AppHookConfig
from aldryn_categories.fields import CategoryManyToManyField
from taggit.managers import TaggableManager
from djangocms_text_ckeditor.fields import HTMLField

from .versioning import version_controlled_content


if settings.LANGUAGES:
    LANGUAGE_CODES = [language[0] for language in settings.LANGUAGES]
elif settings.LANGUAGE:
    LANGUAGE_CODES = [settings.LANGUAGE]
else:
    raise ImproperlyConfigured(
        'Neither LANGUAGES nor LANGUAGE was found in settings.')


class NewsBlogConfig(TranslatableModel, AppHookConfig):
    """Adds some translatable, per-app-instance fields."""
    translations = TranslatedFields(
        app_title=models.CharField(_('application title'), max_length=234),
    )


@python_2_unicode_compatible
@version_controlled_content
class Article(TranslatableModel):
    translations = TranslatedFields(
        title=models.CharField(_('title'), max_length=234),
        slug=models.SlugField(
            verbose_name=_('slug'),
            max_length=255,
            db_index=True,
            blank=True,
            help_text=_(
                'Used in the URL. If changed, the URL will change. '
                'Clear it to have it re-created automatically.'),
        ),
        lead_in=HTMLField(
            verbose_name=_('lead-in'), default='',
            help_text=_('Will be displayed in lists, and at the start of the '
                        'detail page (in bold)')),
        meta_title=models.CharField(
            max_length=255, verbose_name=_('meta title'),
            blank=True, default=''),
        meta_description=models.TextField(
            verbose_name=_('meta description'), blank=True, default=''),
        meta_keywords=models.TextField(
            verbose_name=_('meta keywords'), blank=True, default=''),
        meta={'unique_together': (('language_code', 'slug', ), )},
    )

    content = PlaceholderField('aldryn_newsblog_article_content',
                               related_name='aldryn_newsblog_articles',
                               unique=True)
    author = models.ForeignKey(Person, null=True, blank=True,
        verbose_name=_('author'))
    owner = models.ForeignKey(User, verbose_name=_('owner'))
    namespace = models.ForeignKey(NewsBlogConfig, verbose_name=_('namespace'))
    categories = CategoryManyToManyField('aldryn_categories.Category',
        blank=True, verbose_name=_('categories'))
    tags = TaggableManager(blank=True)
    publishing_date = models.DateTimeField(_('publishing data'))

    featured_image = FilerImageField(null=True, blank=True)

    class Meta:
        ordering = ['-publishing_date']

    def __str__(self):
        return self.safe_translation_getter('title', any_language=True)

    def get_absolute_url(self):
        return reverse('aldryn_newsblog:article-detail', kwargs={
            'slug': self.safe_translation_getter('slug', any_language=True)
        }, current_app=self.namespace.namespace)

    def slugify(self, category, i=None):
        slug = default_slugify(category)
        if i is not None:
            slug += "_%d" % i
        return slug

    def save(self, *args, **kwargs):
        # Ensure there is an owner.
        if self.author is None:
            self.author = Person.objects.get_or_create(
                user=self.owner,
                defaults={
                    'name': u' '.join((self.owner.first_name,
                                       self.owner.last_name))
                })[0]

        # Ensure there is a unique slug.
        if not self.slug:
            self.slug = self.slugify(self.name)
            try:
                return super(Article, self).save(*args, **kwargs)
            except IntegrityError:
                pass

            for lang in LANGUAGE_CODES:
                #
                # We'd much rather just do something like:
                #     Article.objects.translated(lang,
                #         slug__startswith=self.slug)
                # But sadly, this isn't supported by Parler/Django, see:
                #     http://django-parler.readthedocs.org/en/latest/api/\
                #         parler.managers.html#the-translatablequeryset-class
                #
                slugs = []
                all_slugs = Article.objects.language(lang).exclude(
                    id=self.id).values_list('translations__slug', flat=True)
                for slug in all_slugs:
                    if slug and slug.startswith(self.slug):
                        slugs.append(slug)
                i = 1
                while True:
                    slug = self.slugify(self.name, i)
                    if slug not in slugs:
                        self.slug = slug
                        return super(Article, self).save(*args, **kwargs)
                    i += 1
        else:
            return super(Article, self).save(*args, **kwargs)


@python_2_unicode_compatible
class LatestEntriesPlugin(CMSPlugin):

    latest_entries = models.IntegerField(
        default=5,
        help_text=_('The number of latest entries to be displayed.')
    )

    #
    # NOTE: make sure not to forget this if we add m2m/fk fields for
    # _this_plugin_ later:
    #
    # def copy_relations(self, old_instance):
    #     self.categories = old_instance.categories.all()
    #     self.tags = old_instance.tags.all()
    #

    def __str__(self):
        return u'Latest entries: {0}'.format(self.latest_entries)

    def get_articles(self):
        articles = Article.objects.active_translations()
        return articles[:self.latest_entries]
