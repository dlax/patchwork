# Patchwork - automated patch tracking system
# Copyright (C) 2016 Linaro Corporation
#
# This file is part of the Patchwork package.
#
# Patchwork is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Patchwork is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Patchwork; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import email.parser

from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.relations import RelatedField
from rest_framework.serializers import HyperlinkedModelSerializer
from rest_framework.serializers import SerializerMethodField

from patchwork.api.base import PatchworkPermission
from patchwork.api.filters import PatchFilter
from patchwork.models import Patch
from patchwork.models import State


def format_state_name(state):
    return ' '.join(state.split('-'))


class StateField(RelatedField):
    """Avoid the need for a state endpoint.

    NOTE(stephenfin): This field will only function for State names consisting
    of alphanumeric characters, underscores and single spaces. In Patchwork
    2.0+, we should consider adding a slug field to the State object and make
    use of the SlugRelatedField in DRF.
    """
    default_error_messages = {
        'required': _('This field is required.'),
        'invalid_choice': _('Invalid state {name}. Expected one of: {choices}.'),
        'incorrect_type': _('Incorrect type. Expected string value, received '
                            '{data_type}.'),
    }

    def to_internal_value(self, data):
        try:
            data = format_state_name(data)
            return self.get_queryset().get(name__iexact=data)
        except State.DoesNotExist:
            self.fail('invalid_choice', name=data, choices=', '.join([
                format_state_name(x.name) for x in self.get_queryset()]))
        except (TypeError, ValueError):
            self.fail('incorrect_type', data_type=type(data).__name__)

    def to_representation(self, obj):
        return '-'.join(obj.name.lower().split())

    def get_queryset(self):
        return State.objects.all()


class PatchListSerializer(HyperlinkedModelSerializer):
    mbox = SerializerMethodField()
    state = StateField()
    tags = SerializerMethodField()
    check = SerializerMethodField()
    checks = SerializerMethodField()

    def get_mbox(self, instance):
        request = self.context.get('request')
        return request.build_absolute_uri(instance.get_mbox_url())

    def get_tags(self, instance):
        if instance.project.tags:
            return {x.name: getattr(instance, x.attr_name)
                    for x in instance.project.tags}
        else:
            return None

    def get_check(self, instance):
        return instance.combined_check_state

    def get_checks(self, instance):
        return self.context.get('request').build_absolute_uri(
            reverse('api-check-list', kwargs={'patch_id': instance.id}))

    class Meta:
        model = Patch
        fields = ('id', 'url', 'project', 'msgid', 'date', 'name',
                  'commit_ref', 'pull_url', 'state', 'archived', 'hash',
                  'submitter', 'delegate', 'mbox', 'series', 'check', 'checks',
                  'tags')
        read_only_fields = ('project', 'msgid', 'date', 'name', 'hash',
                            'submitter', 'mbox', 'mbox', 'series', 'check',
                            'checks', 'tags')
        extra_kwargs = {
            'url': {'view_name': 'api-patch-detail'},
            'project': {'view_name': 'api-project-detail'},
            'submitter': {'view_name': 'api-person-detail'},
            'delegate': {'view_name': 'api-user-detail'},
            'series': {'view_name': 'api-series-detail',
                       'lookup_url_kwarg': 'pk'},
        }


class PatchDetailSerializer(PatchListSerializer):
    headers = SerializerMethodField()

    def get_headers(self, patch):
        if patch.headers:
            return email.parser.Parser().parsestr(patch.headers, True)

    class Meta:
        model = Patch
        fields = PatchListSerializer.Meta.fields + (
            'headers', 'content', 'diff')
        read_only_fields = PatchListSerializer.Meta.read_only_fields + (
            'headers', 'content', 'diff')
        extra_kwargs = PatchListSerializer.Meta.extra_kwargs


class PatchList(ListAPIView):
    """List patches."""

    permission_classes = (PatchworkPermission,)
    serializer_class = PatchListSerializer
    filter_class = PatchFilter
    search_fields = ('name',)
    ordering_fields = ('id', 'name', 'project', 'date', 'state', 'archived',
                       'submitter', 'check')

    def get_queryset(self):
        return Patch.objects.all().with_tag_counts()\
            .prefetch_related('series', 'check_set')\
            .select_related('state', 'submitter', 'delegate')\
            .defer('content', 'diff', 'headers')


class PatchDetail(RetrieveUpdateAPIView):
    """Show a patch."""

    permission_classes = (PatchworkPermission,)
    serializer_class = PatchDetailSerializer

    def get_queryset(self):
        return Patch.objects.all().with_tag_counts()\
            .prefetch_related('series', 'check_set')\
            .select_related('state', 'submitter', 'delegate')
