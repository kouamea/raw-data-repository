from api.base_api import BaseApi, make_sync_results_for_request
from api_util import PTC_HEALTHPRO_AWARDEE, AWARDEE
from app_util import auth_required, get_validated_user_info
from dao.participant_summary_dao import ParticipantSummaryDao
from flask import request
from werkzeug.exceptions import Forbidden


class ParticipantSummaryApi(BaseApi):
  def __init__(self):
    super(ParticipantSummaryApi, self).__init__(ParticipantSummaryDao())

  @auth_required(PTC_HEALTHPRO_AWARDEE)
  def get(self, p_id=None):
    user_email, user_info = get_validated_user_info()
    if AWARDEE in user_info['roles']:
      user_awardee = user_info['awardee']
      print user_email

    # data only for user_awardee, assert that query has same awardee
    if p_id:
      if user_awardee:
        raise Forbidden
      return super(ParticipantSummaryApi, self).get(p_id)
    else:
      if user_awardee:
        # make sure request ahs awardee
        requested_awardee = request.args.get('awardee')
        if requested_awardee != user_awardee:
          raise Forbidden
      return super(ParticipantSummaryApi, self)._query('participantId')

  def _make_query(self):
    query = super(ParticipantSummaryApi, self)._make_query()
    if self._is_last_modified_sync():
      # roll back last modified time
      for filter in  query.field_filters:
        if filter.field_name == 'lastModified':
          # set time delta subtract
          pass
      query.always_return_token = True
    return query

  def _make_bundle(self, results, id_field, participant_id):
    if self._is_last_modified_sync():
      return make_sync_results_for_request(results)

    return super(ParticipantSummaryApi, self)._make_bundle(results, id_field,
                                                                   participant_id)

  def _is_last_modified_sync(self):
    return request.args.get('_sync') == 'true'
