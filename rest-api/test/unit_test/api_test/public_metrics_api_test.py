import datetime
from clock import FakeClock
from dao.organization_dao import OrganizationDao
from dao.participant_dao import ParticipantDao
from model.hpo import HPO
from dao.hpo_dao import HPODao
from model.code import Code, CodeType
from dao.code_dao import CodeDao
from model.calendar import Calendar
from dao.calendar_dao import CalendarDao
from dao.participant_summary_dao import ParticipantSummaryDao
from test.unit_test.unit_test_util import FlaskTestBase, make_questionnaire_response_json
from model.participant import Participant
from concepts import Concept
from model.participant_summary import ParticipantSummary
from participant_enums import EnrollmentStatus, OrganizationType, TEST_HPO_NAME, TEST_HPO_ID,\
  make_primary_provider_link_for_name, MetricsCacheType
from dao.participant_counts_over_time_service import ParticipantCountsOverTimeService
from dao.metrics_cache_dao import MetricsEnrollmentStatusCacheDao, MetricsGenderCacheDao, \
  MetricsAgeCacheDao, MetricsRaceCacheDao, MetricsRegionCacheDao, MetricsLifecycleCacheDao, \
  MetricsLanguageCacheDao
from code_constants import (PPI_SYSTEM, RACE_WHITE_CODE, RACE_HISPANIC_CODE, RACE_AIAN_CODE,
                            RACE_NONE_OF_THESE_CODE, PMI_SKIP_CODE, RACE_MENA_CODE)

TIME_1 = datetime.datetime(2017, 12, 31)

def _questionnaire_response_url(participant_id):
  return 'Participant/%s/QuestionnaireResponse' % participant_id

class PublicMetricsApiTest(FlaskTestBase):

  provider_link = {
    "primary": True,
    "organization": {
      "display": None,
      "reference": "Organization/PITT",
    }
  }

  az_provider_link = {
    "primary": True,
    "organization": {
      "display": None,
      "reference": "Organization/AZ_TUCSON",
    }
  }

  code_link_ids = (
    'race', 'genderIdentity', 'state', 'sex', 'sexualOrientation', 'recontactMethod', 'language',
    'education', 'income'
  )

  string_link_ids = (
    'firstName', 'middleName', 'lastName', 'streetAddress', 'city', 'phoneNumber', 'zipCode'
  )

  def setUp(self):
    super(PublicMetricsApiTest, self).setUp(use_mysql=True)
    self.dao = ParticipantDao()
    self.ps_dao = ParticipantSummaryDao()
    self.ps = ParticipantSummary()
    self.calendar_dao = CalendarDao()
    self.hpo_dao = HPODao()
    self.org_dao = OrganizationDao()
    self.code_dao = CodeDao()

    self.hpo_dao.insert(HPO(hpoId=TEST_HPO_ID, name=TEST_HPO_NAME, displayName='Test',
                       organizationType=OrganizationType.UNSET))

    self.time1 = datetime.datetime(2017, 12, 31)
    self.time2 = datetime.datetime(2018, 1, 1)
    self.time3 = datetime.datetime(2018, 1, 2)
    self.time4 = datetime.datetime(2018, 1, 3)
    self.time5 = datetime.datetime(2018, 1, 4)

    # Insert 2 weeks of dates
    curr_date = datetime.date(2017, 12, 22)
    for _ in xrange(0, 18):
      calendar_day = Calendar(day=curr_date )
      CalendarDao().insert(calendar_day)
      curr_date = curr_date + datetime.timedelta(days=1)

  def _insert(self, participant, first_name=None, last_name=None, hpo_name=None, org_name=None,
              unconsented=False, time_int=None, time_study=None, time_mem=None, time_fp=None,
              time_fp_stored=None, gender_id=None, dob=None, state_id=None, primary_language=None):
    """
    Create a participant in a transient test database.

    :param participant: Participant object
    :param first_name: First name
    :param last_name: Last name
    :param hpo_name: HPO name (one of PITT or AZ_TUCSON)
    :param org_name: Org external_id (one of PITT_BANNER_HEALTH or AZ_TUCSON_BANNER_HEALTH)
    :param time_int: Time that participant fulfilled INTERESTED criteria
    :param time_mem: Time that participant fulfilled MEMBER criteria
    :param time_fp: Time that participant fulfilled FULL_PARTICIPANT criteria
    :return: Participant object
    """

    if unconsented is True:
      enrollment_status = None
    elif time_mem is None:
      enrollment_status = EnrollmentStatus.INTERESTED
    elif time_fp is None:
      enrollment_status = EnrollmentStatus.MEMBER
    else:
      enrollment_status = EnrollmentStatus.FULL_PARTICIPANT

    with FakeClock(time_int):
      self.dao.insert(participant)

    participant.providerLink = make_primary_provider_link_for_name(hpo_name)
    with FakeClock(time_mem):
      self.dao.update(participant)

    if enrollment_status is None:
      return None

    summary = self.participant_summary(participant)

    if first_name:
      summary.firstName = first_name
    if last_name:
      summary.lastName = last_name

    if gender_id:
      summary.genderIdentityId = gender_id
    if dob:
      summary.dateOfBirth = dob
    else:
      summary.dateOfBirth = datetime.date(1978, 10, 10)
    if state_id:
      summary.stateId = state_id

    if primary_language:
      summary.primaryLanguage = primary_language

    summary.enrollmentStatus = enrollment_status

    summary.enrollmentStatusMemberTime = time_mem
    summary.enrollmentStatusCoreOrderedSampleTime = time_fp
    summary.enrollmentStatusCoreStoredSampleTime = time_fp_stored

    summary.hpoId = self.hpo_dao.get_by_name(hpo_name).hpoId
    if org_name:
      summary.organizationId = self.org_dao.get_by_external_id(org_name).organizationId

    if time_study is not None:
      with FakeClock(time_mem):
        summary.consentForStudyEnrollmentTime = time_study

    if time_mem is not None:
      with FakeClock(time_mem):
        summary.consentForElectronicHealthRecords = 1
        summary.consentForElectronicHealthRecordsTime = time_mem

    if time_fp is not None:
      with FakeClock(time_fp):
        if not summary.consentForElectronicHealthRecords:
          summary.consentForElectronicHealthRecords = 1
          summary.consentForElectronicHealthRecordsTime = time_fp
        summary.questionnaireOnTheBasicsTime = time_fp
        summary.questionnaireOnLifestyleTime = time_fp
        summary.questionnaireOnOverallHealthTime = time_fp
        summary.questionnaireOnHealthcareAccessTime = time_fp
        summary.questionnaireOnMedicalHistoryTime = time_fp
        summary.questionnaireOnMedicationsTime = time_fp
        summary.questionnaireOnFamilyHealthTime = time_fp
        summary.physicalMeasurementsFinalizedTime = time_fp
        summary.physicalMeasurementsTime = time_fp
        summary.sampleOrderStatus1ED04Time = time_fp
        summary.sampleOrderStatus1SALTime = time_fp
        summary.sampleStatus1ED04Time = time_fp
        summary.sampleStatus1SALTime = time_fp

    self.ps_dao.insert(summary)

    return summary

  def update_participant_summary(self, participant_id, time_mem=None, time_fp=None,
                                 time_fp_stored=None, time_study=None):

    participant = self.dao.get(participant_id)
    summary = self.participant_summary(participant)
    if time_mem is None:
      enrollment_status = EnrollmentStatus.INTERESTED
    elif time_fp is None:
      enrollment_status = EnrollmentStatus.MEMBER
    else:
      enrollment_status = EnrollmentStatus.FULL_PARTICIPANT

    summary.enrollmentStatus = enrollment_status

    summary.enrollmentStatusMemberTime = time_mem
    summary.enrollmentStatusCoreOrderedSampleTime = time_fp
    summary.enrollmentStatusCoreStoredSampleTime = time_fp_stored

    if time_study is not None:
      with FakeClock(time_mem):
        summary.consentForStudyEnrollmentTime = time_study

    if time_mem is not None:
      with FakeClock(time_mem):
        summary.consentForElectronicHealthRecords = 1
        summary.consentForElectronicHealthRecordsTime = time_mem

    if time_fp is not None:
      with FakeClock(time_fp):
        if not summary.consentForElectronicHealthRecords:
          summary.consentForElectronicHealthRecords = 1
          summary.consentForElectronicHealthRecordsTime = time_fp
        summary.questionnaireOnTheBasicsTime = time_fp
        summary.questionnaireOnLifestyleTime = time_fp
        summary.questionnaireOnOverallHealthTime = time_fp
        summary.questionnaireOnHealthcareAccessTime = time_fp
        summary.questionnaireOnMedicalHistoryTime = time_fp
        summary.questionnaireOnMedicationsTime = time_fp
        summary.questionnaireOnFamilyHealthTime = time_fp
        summary.physicalMeasurementsFinalizedTime = time_fp
        summary.physicalMeasurementsTime = time_fp
        summary.sampleOrderStatus1ED04Time = time_fp
        summary.sampleOrderStatus1SALTime = time_fp
        summary.sampleStatus1ED04Time = time_fp
        summary.sampleStatus1SALTime = time_fp

    self.ps_dao.update(summary)

    return summary

  def test_public_metrics_get_enrollment_status_api(self):

    p1 = Participant(participantId=1, biobankId=4)
    self._insert(p1, 'Alice', 'Aardvark', 'UNSET', unconsented=True, time_int=self.time1)

    p2 = Participant(participantId=2, biobankId=5)
    self._insert(p2, 'Bob', 'Builder', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time2)

    p3 = Participant(participantId=3, biobankId=6)
    self._insert(p3, 'Chad', 'Caterpillar', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time1, time_mem=self.time3, time_fp_stored=self.time4)

    service = ParticipantCountsOverTimeService()
    dao = MetricsEnrollmentStatusCacheDao(MetricsCacheType.PUBLIC_METRICS_EXPORT_API)
    service.refresh_data_for_metrics_cache(dao)

    qs = (
          '&stratification=ENROLLMENT_STATUS'
          '&startDate=2018-01-01'
          '&endDate=2018-01-08'
          )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({'date': '2018-01-01', 'metrics': {'consented': 0, 'core': 0, 'registered': 3}},
                  results)
    self.assertIn({'date': '2018-01-02', 'metrics': {'consented': 1, 'core': 0, 'registered': 2}},
                  results)
    self.assertIn({'date': '2018-01-03', 'metrics': {'consented': 0, 'core': 1, 'registered': 2}},
                  results)

    qs = (
          '&stratification=ENROLLMENT_STATUS'
          '&startDate=2018-01-01'
          '&endDate=2018-01-08'
          '&awardee=AZ_TUCSON'
          )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({'date': '2018-01-01', 'metrics': {'consented': 0, 'core': 0, 'registered': 2}},
                  results)
    self.assertIn({'date': '2018-01-02', 'metrics': {'consented': 1, 'core': 0, 'registered': 1}},
                  results)
    self.assertIn({'date': '2018-01-03', 'metrics': {'consented': 0, 'core': 1, 'registered': 1}},
                  results)

  def test_public_metrics_get_gender_api(self):

    code1 = Code(codeId=354, system="a", value="a", display=u"a", topic=u"a",
                 codeType=CodeType.MODULE, mapped=True)
    code2 = Code(codeId=356, system="b", value="b", display=u"b", topic=u"b",
                 codeType=CodeType.MODULE, mapped=True)
    code3 = Code(codeId=355, system="c", value="c", display=u"c", topic=u"c",
                 codeType=CodeType.MODULE, mapped=True)

    self.code_dao.insert(code1)
    self.code_dao.insert(code2)
    self.code_dao.insert(code3)

    p1 = Participant(participantId=1, biobankId=4)
    self._insert(p1, 'Alice', 'Aardvark', 'UNSET', time_int=self.time1, gender_id=354)

    p2 = Participant(participantId=2, biobankId=5)
    self._insert(p2, 'Bob', 'Builder', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time2,
                 time_mem=self.time3, gender_id=356)

    p3 = Participant(participantId=3, biobankId=6)
    self._insert(p3, 'Chad', 'Caterpillar', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time3, time_mem=self.time5, gender_id=355)

    p4 = Participant(participantId=4, biobankId=7)
    self._insert(p4, 'Chad2', 'Caterpillar2', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time4, time_mem=self.time5, gender_id=355)

    # ghost participant should be filtered out
    p_ghost = Participant(participantId=5, biobankId=8, isGhostId=True)
    self._insert(p_ghost, 'Ghost', 'G', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time1, gender_id=355)

    service = ParticipantCountsOverTimeService()
    dao = MetricsGenderCacheDao(MetricsCacheType.PUBLIC_METRICS_EXPORT_API)
    service.refresh_data_for_metrics_cache(dao)

    qs = (
          '&stratification=GENDER_IDENTITY'
          '&startDate=2017-12-31'
          '&endDate=2018-01-08'
          )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({'date': '2017-12-31',
                   'metrics': {u'Woman': 1, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 0,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 0}}, results)
    self.assertIn({'date': '2018-01-01',
                   'metrics': {u'Woman': 1, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 0,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 1}}, results)
    self.assertIn({'date': '2018-01-02',
                   'metrics': {u'Woman': 1, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 1,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 1}}, results)
    self.assertIn({'date': '2018-01-03',
                   'metrics': {u'Woman': 1, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 2,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 1}}, results)

    qs = (
          '&stratification=GENDER_IDENTITY'
          '&startDate=2017-12-31'
          '&endDate=2018-01-08'
          '&awardee=AZ_TUCSON'
          )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({'date': '2017-12-31',
                   'metrics': {u'Woman': 0, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 0,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 0}}, results)
    self.assertIn({'date': '2018-01-01',
                   'metrics': {u'Woman': 0, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 0,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 1}}, results)
    self.assertIn({'date': '2018-01-02',
                   'metrics': {u'Woman': 0, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 1,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 1}}, results)
    self.assertIn({'date': '2018-01-03',
                   'metrics': {u'Woman': 0, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 2,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 1}}, results)

    qs = (
      '&stratification=GENDER_IDENTITY'
      '&startDate=2017-12-31'
      '&endDate=2018-01-08'
      '&awardee=AZ_TUCSON'
      '&enrollmentStatus=MEMBER'
    )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({'date': '2017-12-31',
                   'metrics': {u'Woman': 0, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 0,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 0}}, results)
    self.assertIn({'date': '2018-01-01',
                   'metrics': {u'Woman': 0, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 0,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 0}}, results)
    self.assertIn({'date': '2018-01-02',
                   'metrics': {u'Woman': 0, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 0,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 1}}, results)
    self.assertIn({'date': '2018-01-04',
                   'metrics': {u'Woman': 0, u'PMI_Skip': 0, u'Other/Additional Options': 0,
                               u'Non-Binary': 0, 'UNMAPPED': 0, u'Transgender': 2,
                               u'Prefer not to say': 0, u'UNSET': 0, u'Man': 1}}, results)

  def test_public_metrics_get_age_range_api(self):

    dob1 = datetime.date(1978, 10, 10)
    dob2 = datetime.date(1988, 10, 10)
    dob3 = datetime.date(1988, 10, 10)
    dob4 = datetime.date(1998, 10, 10)
    p1 = Participant(participantId=1, biobankId=4)
    self._insert(p1, 'Alice', 'Aardvark', 'UNSET', time_int=self.time1, dob=dob1)

    p2 = Participant(participantId=2, biobankId=5)
    self._insert(p2, 'Bob', 'Builder', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time2,
                 time_mem=self.time3, dob=dob2)

    p3 = Participant(participantId=3, biobankId=6)
    self._insert(p3, 'Chad', 'Caterpillar', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time3, time_mem=self.time5, dob=dob3)

    p4 = Participant(participantId=4, biobankId=7)
    self._insert(p4, 'Chad2', 'Caterpillar2', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time4, time_mem=self.time5, dob=dob4)

    # ghost participant should be filtered out
    p_ghost = Participant(participantId=5, biobankId=8, isGhostId=True)
    self._insert(p_ghost, 'Ghost', 'G', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time1,
                 dob=dob3)

    service = ParticipantCountsOverTimeService()
    dao = MetricsAgeCacheDao(MetricsCacheType.PUBLIC_METRICS_EXPORT_API)
    service.refresh_data_for_metrics_cache(dao)

    qs = (
          '&stratification=AGE_RANGE'
          '&startDate=2017-12-31'
          '&endDate=2018-01-08'
          )

    results = self.send_get('PublicMetrics', query_string=qs)

    self.assertIn({'date': '2017-12-31',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 1, u'40-49': 0, u'UNSET': 0,
                               u'80-89': 0, u'90-': 0, u'18-29': 0, u'70-79': 0}}, results)
    self.assertIn({'date': '2018-01-01',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 1, u'40-49': 0, u'18-29': 1,
                               u'80-89': 0, u'90-': 0, u'UNSET': 0, u'70-79': 0}}, results)
    self.assertIn({'date': '2018-01-02',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 1, u'40-49': 0, u'18-29': 2,
                               u'80-89': 0, u'70-79': 0, u'UNSET': 0, u'90-': 0}}, results)
    self.assertIn({'date': '2018-01-03',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 1, u'40-49': 0, u'18-29': 3,
                               u'80-89': 0, u'70-79': 0, u'UNSET': 0, u'90-': 0}}, results)

    qs = (
          '&stratification=AGE_RANGE'
          '&startDate=2017-12-31'
          '&endDate=2018-01-08'
          '&awardee=AZ_TUCSON'
          )

    results = self.send_get('PublicMetrics', query_string=qs)

    self.assertIn({'date': '2017-12-31',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 0, u'40-49': 0, u'UNSET': 0,
                               u'80-89': 0, u'90-': 0, u'18-29': 0, u'70-79': 0}}, results)
    self.assertIn({'date': '2018-01-01',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 0, u'40-49': 0, u'18-29': 1,
                               u'80-89': 0, u'90-': 0, u'UNSET': 0, u'70-79': 0}}, results)
    self.assertIn({'date': '2018-01-02',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 0, u'40-49': 0, u'18-29': 2,
                               u'80-89': 0, u'70-79': 0, u'UNSET': 0, u'90-': 0}}, results)
    self.assertIn({'date': '2018-01-03',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 0, u'40-49': 0, u'18-29': 3,
                               u'80-89': 0, u'70-79': 0, u'UNSET': 0, u'90-': 0}}, results)

    qs = (
      '&stratification=AGE_RANGE'
      '&startDate=2017-12-31'
      '&endDate=2018-01-08'
      '&awardee=AZ_TUCSON'
      '&enrollmentStatus=MEMBER'
    )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({'date': '2017-12-31',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 0, u'40-49': 0, u'UNSET': 0,
                               u'80-89': 0, u'90-': 0, u'18-29': 0, u'70-79': 0}}, results)
    self.assertIn({'date': '2018-01-01',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 0, u'40-49': 0, u'18-29': 0,
                               u'80-89': 0, u'90-': 0, u'UNSET': 0, u'70-79': 0}}, results)
    self.assertIn({'date': '2018-01-02',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 0, u'40-49': 0, u'18-29': 1,
                               u'80-89': 0, u'70-79': 0, u'UNSET': 0, u'90-': 0}}, results)
    self.assertIn({'date': '2018-01-03',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 0, u'40-49': 0, u'18-29': 1,
                               u'80-89': 0, u'70-79': 0, u'UNSET': 0, u'90-': 0}}, results)
    self.assertIn({'date': '2018-01-04',
                   'metrics': {u'50-59': 0, u'60-69': 0, u'30-39': 0, u'40-49': 0, u'18-29': 3,
                               u'80-89': 0, u'70-79': 0, u'UNSET': 0, u'90-': 0}}, results)

  def test_public_metrics_get_total_api(self):

    p1 = Participant(participantId=1, biobankId=4)
    self._insert(p1, 'Alice', 'Aardvark', 'UNSET', unconsented=True, time_int=self.time1)

    p2 = Participant(participantId=2, biobankId=5)
    self._insert(p2, 'Bob', 'Builder', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time2)

    p3 = Participant(participantId=3, biobankId=6)
    self._insert(p3, 'Chad', 'Caterpillar', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time3, time_mem=self.time4, time_fp_stored=self.time5)

    # ghost participant should be filtered out
    p_ghost = Participant(participantId=5, biobankId=8, isGhostId=True)
    self._insert(p_ghost, 'Ghost', 'G', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time1,
                 time_mem=self.time4, time_fp_stored=self.time5)

    service = ParticipantCountsOverTimeService()
    dao = MetricsEnrollmentStatusCacheDao()
    service.refresh_data_for_metrics_cache(dao)

    qs = (
          '&stratification=TOTAL'
          '&startDate=2018-01-01'
          '&endDate=2018-01-08'
          )

    response = self.send_get('PublicMetrics', query_string=qs)

    self.assertIn({u'date': u'2018-01-01', u'metrics': {u'TOTAL': 2}}, response)
    self.assertIn({u'date': u'2018-01-02', u'metrics': {u'TOTAL': 3}}, response)
    self.assertIn({u'date': u'2018-01-07', u'metrics': {u'TOTAL': 3}}, response)
    self.assertIn({u'date': u'2018-01-08', u'metrics': {u'TOTAL': 3}}, response)

    qs = (
          '&stratification=TOTAL'
          '&startDate=2018-01-01'
          '&endDate=2018-01-08'
          '&awardee=AZ_TUCSON'
          )

    response = self.send_get('PublicMetrics', query_string=qs)

    self.assertIn({u'date': u'2018-01-01', u'metrics': {u'TOTAL': 1}}, response)
    self.assertIn({u'date': u'2018-01-02', u'metrics': {u'TOTAL': 2}}, response)
    self.assertIn({u'date': u'2018-01-07', u'metrics': {u'TOTAL': 2}}, response)
    self.assertIn({u'date': u'2018-01-08', u'metrics': {u'TOTAL': 2}}, response)

  def test_public_metrics_get_race_api(self):

    questionnaire_id = self.create_demographics_questionnaire()

    def setup_participant(when, race_code_list, providerLink=self.provider_link):
      # Set up participant, questionnaire, and consent
      with FakeClock(when):
        participant = self.send_post('Participant', {"providerLink": [providerLink]})
        participant_id = participant['participantId']
        self.send_consent(participant_id)
        # Populate some answers to the questionnaire
        answers = {
          'race': race_code_list,
          'genderIdentity': PMI_SKIP_CODE,
          'firstName': self.fake.first_name(),
          'middleName': self.fake.first_name(),
          'lastName': self.fake.last_name(),
          'zipCode': '78751',
          'state': PMI_SKIP_CODE,
          'streetAddress': '1234 Main Street',
          'city': 'Austin',
          'sex': PMI_SKIP_CODE,
          'sexualOrientation': PMI_SKIP_CODE,
          'phoneNumber': '512-555-5555',
          'recontactMethod': PMI_SKIP_CODE,
          'language': PMI_SKIP_CODE,
          'education': PMI_SKIP_CODE,
          'income': PMI_SKIP_CODE,
          'dateOfBirth': datetime.date(1978, 10, 9),
          'CABoRSignature': 'signature.pdf',
        }
      self.post_demographics_questionnaire(participant_id, questionnaire_id, time=when, **answers)
      return participant

    p1 = setup_participant(self.time1, [RACE_WHITE_CODE, RACE_HISPANIC_CODE], self.provider_link)
    self.update_participant_summary(p1['participantId'][1:], time_mem=self.time2)
    p2 = setup_participant(self.time2, [RACE_NONE_OF_THESE_CODE], self.provider_link)
    self.update_participant_summary(p2['participantId'][1:], time_mem=self.time3,
                                    time_fp_stored=self.time5)
    p3 = setup_participant(self.time3, [RACE_AIAN_CODE], self.provider_link)
    self.update_participant_summary(p3['participantId'][1:], time_mem=self.time4)
    p4 = setup_participant(self.time4, [PMI_SKIP_CODE], self.provider_link)
    self.update_participant_summary(p4['participantId'][1:], time_mem=self.time5)
    p5 = setup_participant(self.time4, [RACE_WHITE_CODE, RACE_HISPANIC_CODE], self.provider_link)
    self.update_participant_summary(p5['participantId'][1:], time_mem=self.time4,
                                    time_fp_stored=self.time5)
    setup_participant(self.time2, [RACE_AIAN_CODE], self.az_provider_link)
    setup_participant(self.time3, [RACE_AIAN_CODE, RACE_MENA_CODE], self.az_provider_link)

    service = ParticipantCountsOverTimeService()
    dao = MetricsRaceCacheDao(MetricsCacheType.PUBLIC_METRICS_EXPORT_API)
    service.refresh_data_for_metrics_cache(dao)

    qs = (
          '&stratification=RACE'
          '&startDate=2017-12-31'
          '&endDate=2018-01-08'
          )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({'date': '2017-12-31',
                   'metrics': {'None_Of_These_Fully_Describe_Me': 0,
                               'Middle_Eastern_North_African': 0,
                               'Multi_Ancestry': 1,
                               'American_Indian_Alaska_Native': 0,
                               'No_Ancestry_Checked': 0,
                               'Black_African_American': 0,
                               'White': 0,
                               'Prefer_Not_To_Answer': 0,
                               'Hispanic_Latino_Spanish': 0,
                               'Native_Hawaiian_other_Pacific_Islander': 0,
                               'Asian': 0}}, results)
    self.assertIn({'date': '2018-01-01',
                   'metrics': {'None_Of_These_Fully_Describe_Me': 1,
                               'Middle_Eastern_North_African': 0,
                               'Multi_Ancestry': 1,
                               'American_Indian_Alaska_Native': 1,
                               'No_Ancestry_Checked': 0,
                               'Black_African_American': 0,
                               'White': 0,
                               'Prefer_Not_To_Answer': 0,
                               'Hispanic_Latino_Spanish': 0,
                               'Native_Hawaiian_other_Pacific_Islander': 0,
                               'Asian': 0}}, results)
    self.assertIn({'date': '2018-01-02',
                   'metrics': {'None_Of_These_Fully_Describe_Me': 1,
                               'Middle_Eastern_North_African': 0,
                               'Multi_Ancestry': 2,
                               'American_Indian_Alaska_Native': 2,
                               'No_Ancestry_Checked': 0,
                               'Black_African_American': 0,
                               'White': 0,
                               'Prefer_Not_To_Answer': 0,
                               'Hispanic_Latino_Spanish': 0,
                               'Native_Hawaiian_other_Pacific_Islander': 0,
                               'Asian': 0}}, results)

    qs = (
          '&stratification=RACE'
          '&startDate=2017-12-31'
          '&endDate=2018-01-08'
          '&awardee=AZ_TUCSON'
          )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({'date': '2018-01-01',
                   'metrics': {'None_Of_These_Fully_Describe_Me': 0,
                               'Middle_Eastern_North_African': 0,
                               'Multi_Ancestry': 0,
                               'American_Indian_Alaska_Native': 1,
                               'No_Ancestry_Checked': 0,
                               'Black_African_American': 0,
                               'White': 0,
                               'Prefer_Not_To_Answer': 0,
                               'Hispanic_Latino_Spanish': 0,
                               'Native_Hawaiian_other_Pacific_Islander': 0,
                               'Asian': 0}}, results)
    self.assertIn({'date': '2018-01-02',
                   'metrics': {'None_Of_These_Fully_Describe_Me': 0,
                               'Middle_Eastern_North_African': 0,
                               'Multi_Ancestry': 1,
                               'American_Indian_Alaska_Native': 1,
                               'No_Ancestry_Checked': 0,
                               'Black_African_American': 0,
                               'White': 0,
                               'Prefer_Not_To_Answer': 0,
                               'Hispanic_Latino_Spanish': 0,
                               'Native_Hawaiian_other_Pacific_Islander': 0,
                               'Asian': 0}}, results)

    qs = (
      '&stratification=RACE'
      '&startDate=2017-12-31'
      '&endDate=2018-01-08'
      '&awardee=PITT'
      '&enrollmentStatus=MEMBER'
    )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({'date': '2018-01-03',
                   'metrics': {'None_Of_These_Fully_Describe_Me': 1,
                               'Middle_Eastern_North_African': 0,
                               'Multi_Ancestry': 2,
                               'American_Indian_Alaska_Native': 1,
                               'No_Ancestry_Checked': 0,
                               'Black_African_American': 0,
                               'White': 0,
                               'Prefer_Not_To_Answer': 0,
                               'Hispanic_Latino_Spanish': 0,
                               'Native_Hawaiian_other_Pacific_Islander': 0,
                               'Asian': 0}}, results)
    self.assertIn({'date': '2018-01-04',
                   'metrics': {'None_Of_These_Fully_Describe_Me': 0,
                               'Middle_Eastern_North_African': 0,
                               'Multi_Ancestry': 1,
                               'American_Indian_Alaska_Native': 1,
                               'No_Ancestry_Checked': 1,
                               'Black_African_American': 0,
                               'White': 0,
                               'Prefer_Not_To_Answer': 0,
                               'Hispanic_Latino_Spanish': 0,
                               'Native_Hawaiian_other_Pacific_Islander': 0,
                               'Asian': 0}}, results)

  def test_public_metrics_get_region_api(self):

    code1 = Code(codeId=1, system="a", value="PIIState_IL", display=u"PIIState_IL", topic=u"a",
                 codeType=CodeType.MODULE, mapped=True)
    code2 = Code(codeId=2, system="b", value="PIIState_IN", display=u"PIIState_IN", topic=u"b",
                 codeType=CodeType.MODULE, mapped=True)
    code3 = Code(codeId=3, system="c", value="PIIState_CA", display=u"PIIState_CA", topic=u"c",
                 codeType=CodeType.MODULE, mapped=True)

    self.code_dao.insert(code1)
    self.code_dao.insert(code2)
    self.code_dao.insert(code3)

    p1 = Participant(participantId=1, biobankId=4)
    self._insert(p1, 'Alice', 'Aardvark', 'UNSET', time_int=self.time1, time_mem=self.time1,
                 time_fp_stored=self.time1, state_id=1)

    p2 = Participant(participantId=2, biobankId=5)
    self._insert(p2, 'Bob', 'Builder', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time2,
                 time_mem=self.time2, time_fp_stored=self.time2, state_id=2)

    p3 = Participant(participantId=3, biobankId=6)
    self._insert(p3, 'Chad', 'Caterpillar', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time3, time_mem=self.time3, time_fp_stored=self.time3, state_id=3)

    p4 = Participant(participantId=4, biobankId=7)
    self._insert(p4, 'Chad2', 'Caterpillar2', 'PITT', 'PITT_BANNER_HEALTH', time_int=self.time3,
                 time_mem=self.time3, time_fp_stored=self.time3, state_id=2)

    p5 = Participant(participantId=6, biobankId=9)
    self._insert(p5, 'Chad3', 'Caterpillar3', 'PITT', 'PITT_BANNER_HEALTH', time_int=self.time1,
                 time_mem=self.time2, time_fp_stored=self.time3, state_id=2)

    # ghost participant should be filtered out
    p_ghost = Participant(participantId=5, biobankId=8, isGhostId=True)
    self._insert(p_ghost, 'Ghost', 'G', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time1,
                 time_mem=self.time1, time_fp_stored=self.time1, state_id=1)

    service = ParticipantCountsOverTimeService()
    dao = MetricsRegionCacheDao(MetricsCacheType.PUBLIC_METRICS_EXPORT_API)
    service.refresh_data_for_metrics_cache(dao)

    qs1 = (
            '&stratification=GEO_STATE'
            '&endDate=2017-12-31'
            )

    results1 = self.send_get('PublicMetrics', query_string=qs1)

    qs2 = (
            '&stratification=GEO_CENSUS'
            '&endDate=2018-01-01'
            )

    results2 = self.send_get('PublicMetrics', query_string=qs2)

    qs3 = (
            '&stratification=GEO_AWARDEE'
            '&endDate=2018-01-02'
            )

    results3 = self.send_get('PublicMetrics', query_string=qs3)

    self.assertIn({'date': '2017-12-31',
                   'metrics': {'WA': 0, 'DE': 0, 'DC': 0, 'WI': 0, 'WV': 0, 'HI': 0,
                               'FL': 0, 'WY': 0, 'NH': 0, 'NJ': 0, 'NM': 0, 'TX': 0,
                               'LA': 0, 'AK': 0, 'NC': 0, 'ND': 0, 'NE': 0, 'TN': 0,
                               'NY': 0, 'PA': 0, 'RI': 0, 'NV': 0, 'VA': 0, 'CO': 0,
                               'CA': 0, 'AL': 0, 'AR': 0, 'VT': 0, 'IL': 1, 'GA': 0,
                               'IN': 1, 'IA': 0, 'MA': 0, 'AZ': 0, 'ID': 0, 'CT': 0,
                               'ME': 0, 'MD': 0, 'OK': 0, 'OH': 0, 'UT': 0, 'MO': 0,
                               'MN': 0, 'MI': 0, 'KS': 0, 'MT': 0, 'MS': 0, 'SC': 0,
                               'KY': 0, 'OR': 0, 'SD': 0}}, results1)
    self.assertIn({'date': '2018-01-01',
                  'metrics': {'WEST': 0, 'NORTHEAST': 0, 'MIDWEST': 3,
                              'SOUTH': 0}}, results2)
    self.assertIn({'date': '2018-01-02', 'count': 1, 'hpo': u'UNSET'}, results3)
    self.assertIn({'date': '2018-01-02', 'count': 2, 'hpo': u'PITT'}, results3)
    self.assertIn({'date': '2018-01-02', 'count': 2, 'hpo': u'AZ_TUCSON'}, results3)

  def test_public_metrics_get_lifecycle_api(self):

    p1 = Participant(participantId=1, biobankId=4)
    self._insert(p1, 'Alice', 'Aardvark', 'UNSET', time_int=self.time1, time_study=self.time1,
                 time_mem=self.time1, time_fp=self.time1, time_fp_stored=self.time1)

    p2 = Participant(participantId=2, biobankId=5)
    self._insert(p2, 'Bob', 'Builder', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time2,
                 time_study=self.time2, time_mem=self.time2, time_fp=self.time3,
                 time_fp_stored=self.time3)

    p3 = Participant(participantId=3, biobankId=6)
    self._insert(p3, 'Chad', 'Caterpillar', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time3, time_study=self.time4, time_mem=self.time4,
                 time_fp=self.time5, time_fp_stored=self.time5)

    p4 = Participant(participantId=4, biobankId=7)
    self._insert(p4, 'Chad2', 'Caterpillar2', 'PITT', 'PITT_BANNER_HEALTH', time_int=self.time3,
                 time_study=self.time4, time_mem=self.time5, time_fp=self.time5,
                 time_fp_stored=self.time5)

    p4 = Participant(participantId=6, biobankId=9)
    self._insert(p4, 'Chad3', 'Caterpillar3', 'PITT', 'PITT_BANNER_HEALTH', time_int=self.time3,
                 time_study=self.time4, time_mem=self.time4, time_fp=self.time4,
                 time_fp_stored=self.time5)

    # ghost participant should be filtered out
    p_ghost = Participant(participantId=5, biobankId=8, isGhostId=True)
    self._insert(p_ghost, 'Ghost', 'G', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time1,
                 time_study=self.time1, time_mem=self.time1, time_fp=self.time1,
                 time_fp_stored=self.time1)

    service = ParticipantCountsOverTimeService()
    dao = MetricsLifecycleCacheDao(MetricsCacheType.PUBLIC_METRICS_EXPORT_API)
    service.refresh_data_for_metrics_cache(dao)

    qs1 = (
            '&stratification=LIFECYCLE'
            '&endDate=2018-01-03'
            )

    results1 = self.send_get('PublicMetrics', query_string=qs1)
    self.assertEquals(results1, [{'date': '2018-01-03',
                                 'metrics': {
                                   'not_completed': {
                                     'Full_Participant': 3, 'PPI_Module_The_Basics': 2,
                                     'Consent_Complete': 1, 'Consent_Enrollment': 0,
                                     'PPI_Module_Lifestyle': 2, 'Baseline_PPI_Modules_Complete': 2,
                                     'PPI_Module_Family_Health': 2, 'PPI_Module_Overall_Health': 2,
                                     'PPI_Module_Medications': 2,  'Physical_Measurements': 2,
                                     'Registered': 0, 'PPI_Module_Medical_History': 2,
                                     'PPI_Module_Healthcare_Access': 2, 'Samples_Received': 2},
                                   'completed': {
                                     'Full_Participant': 2, 'PPI_Module_The_Basics': 3,
                                     'Consent_Complete': 4, 'Consent_Enrollment': 5,
                                     'PPI_Module_Lifestyle': 3, 'Baseline_PPI_Modules_Complete': 3,
                                     'PPI_Module_Family_Health': 3, 'PPI_Module_Overall_Health': 3,
                                     'PPI_Module_Medications': 3, 'Physical_Measurements': 3,
                                     'Registered': 5, 'PPI_Module_Medical_History': 3,
                                     'PPI_Module_Healthcare_Access': 3, 'Samples_Received': 3}
                                   }
                                 }])

    qs2 = (
            '&stratification=LIFECYCLE'
            '&endDate=2018-01-08'
            )

    results2 = self.send_get('PublicMetrics', query_string=qs2)
    self.assertEquals(results2, [{'date': '2018-01-08',
                                  'metrics': {
                                    'not_completed': {
                                      'Full_Participant': 0, 'PPI_Module_The_Basics': 0,
                                      'Consent_Complete': 0, 'Consent_Enrollment': 0,
                                      'PPI_Module_Lifestyle': 0, 'Baseline_PPI_Modules_Complete': 0,
                                      'PPI_Module_Family_Health': 0, 'PPI_Module_Overall_Health': 0,
                                      'PPI_Module_Medications': 0, 'Physical_Measurements': 0,
                                      'Registered': 0, 'PPI_Module_Medical_History': 0,
                                      'PPI_Module_Healthcare_Access': 0, 'Samples_Received': 0},
                                    'completed': {
                                      'Full_Participant': 5, 'PPI_Module_The_Basics': 5,
                                      'Consent_Complete': 5, 'Consent_Enrollment': 5,
                                      'PPI_Module_Lifestyle': 5, 'Baseline_PPI_Modules_Complete': 5,
                                      'PPI_Module_Family_Health': 5, 'PPI_Module_Overall_Health': 5,
                                      'PPI_Module_Medications': 5, 'Physical_Measurements': 5,
                                      'Registered': 5, 'PPI_Module_Medical_History': 5,
                                      'PPI_Module_Healthcare_Access': 5, 'Samples_Received': 5}
                                    }
                                  }])

  def test_public_metrics_get_language_api(self):

    p1 = Participant(participantId=1, biobankId=4)
    self._insert(p1, 'Alice', 'Aardvark', 'UNSET', unconsented=True, time_int=self.time1,
                 primary_language='en')

    p2 = Participant(participantId=2, biobankId=5)
    self._insert(p2, 'Bob', 'Builder', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time2,
                 primary_language='es')

    p3 = Participant(participantId=3, biobankId=6)
    self._insert(p3, 'Chad', 'Caterpillar', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time1, time_mem=self.time3, time_fp_stored=self.time4,
                 primary_language='en')

    p4 = Participant(participantId=5, biobankId=7)
    self._insert(p4, 'Chad2', 'Caterpillar2', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time1, time_mem=self.time2, time_fp_stored=self.time4)

    service = ParticipantCountsOverTimeService()
    dao = MetricsLanguageCacheDao(MetricsCacheType.PUBLIC_METRICS_EXPORT_API)
    service.refresh_data_for_metrics_cache(dao)
    qs = (
          '&stratification=LANGUAGE'
          '&startDate=2017-12-30'
          '&endDate=2018-01-03'
          )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({'date': '2017-12-30', 'metrics': {'EN': 0, 'UNSET': 0, 'ES': 0}}, results)
    self.assertIn({'date': '2017-12-31', 'metrics': {'EN': 1, 'UNSET': 2, 'ES': 0}}, results)
    self.assertIn({'date': '2018-01-03', 'metrics': {'EN': 1, 'UNSET': 2, 'ES': 1}}, results)

  def test_public_metrics_get_primary_consent_api(self):

    p1 = Participant(participantId=1, biobankId=4)
    self._insert(p1, 'Alice', 'Aardvark', 'UNSET', time_int=self.time1, time_study=self.time1,
                 time_mem=self.time1, time_fp=self.time1, time_fp_stored=self.time1)

    p2 = Participant(participantId=2, biobankId=5)
    self._insert(p2, 'Bob', 'Builder', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time2,
                 time_study=self.time2, time_mem=self.time2, time_fp=self.time3,
                 time_fp_stored=self.time3)

    p3 = Participant(participantId=3, biobankId=6)
    self._insert(p3, 'Chad', 'Caterpillar', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time3, time_study=self.time4, time_mem=self.time4,
                 time_fp=self.time5, time_fp_stored=self.time5)

    p4 = Participant(participantId=4, biobankId=7)
    self._insert(p4, 'Chad2', 'Caterpillar2', 'PITT', 'PITT_BANNER_HEALTH', time_int=self.time3,
                 time_study=self.time4, time_mem=self.time5, time_fp=self.time5,
                 time_fp_stored=self.time5)

    p4 = Participant(participantId=6, biobankId=9)
    self._insert(p4, 'Chad3', 'Caterpillar3', 'PITT', 'PITT_BANNER_HEALTH', time_int=self.time3,
                 time_study=self.time4, time_mem=self.time4, time_fp=self.time4,
                 time_fp_stored=self.time5)

    # ghost participant should be filtered out
    p_ghost = Participant(participantId=5, biobankId=8, isGhostId=True)
    self._insert(p_ghost, 'Ghost', 'G', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time1,
                 time_study=self.time1, time_mem=self.time1, time_fp=self.time1,
                 time_fp_stored=self.time1)

    service = ParticipantCountsOverTimeService()
    dao = MetricsLifecycleCacheDao(MetricsCacheType.PUBLIC_METRICS_EXPORT_API)
    service.refresh_data_for_metrics_cache(dao)

    qs = (
          '&stratification=PRIMARY_CONSENT'
          '&startDate=2017-12-31'
          '&endDate=2018-01-08'
          )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({u'date': u'2017-12-31', u'metrics': {u'Primary_Consent': 1}}, results)
    self.assertIn({u'date': u'2018-01-02', u'metrics': {u'Primary_Consent': 2}}, results)
    self.assertIn({u'date': u'2018-01-06', u'metrics': {u'Primary_Consent': 5}}, results)

  def test_public_metrics_get_ehr_consent_api(self):

    p1 = Participant(participantId=1, biobankId=4)
    self._insert(p1, 'Alice', 'Aardvark', 'UNSET', time_int=self.time1, time_study=self.time1,
                 time_mem=self.time1, time_fp=self.time1, time_fp_stored=self.time1)

    p2 = Participant(participantId=2, biobankId=5)
    self._insert(p2, 'Bob', 'Builder', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time2,
                 time_study=self.time2, time_mem=self.time2, time_fp=self.time3,
                 time_fp_stored=self.time3)

    p3 = Participant(participantId=3, biobankId=6)
    self._insert(p3, 'Chad', 'Caterpillar', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH',
                 time_int=self.time3, time_study=self.time4, time_mem=self.time4,
                 time_fp=self.time5, time_fp_stored=self.time5)

    p4 = Participant(participantId=4, biobankId=7)
    self._insert(p4, 'Chad2', 'Caterpillar2', 'PITT', 'PITT_BANNER_HEALTH', time_int=self.time3,
                 time_study=self.time4, time_mem=self.time5, time_fp=self.time5,
                 time_fp_stored=self.time5)

    p4 = Participant(participantId=6, biobankId=9)
    self._insert(p4, 'Chad3', 'Caterpillar3', 'PITT', 'PITT_BANNER_HEALTH', time_int=self.time3,
                 time_study=self.time4, time_mem=self.time4, time_fp=self.time4,
                 time_fp_stored=self.time5)

    # ghost participant should be filtered out
    p_ghost = Participant(participantId=5, biobankId=8, isGhostId=True)
    self._insert(p_ghost, 'Ghost', 'G', 'AZ_TUCSON', 'AZ_TUCSON_BANNER_HEALTH', time_int=self.time1,
                 time_study=self.time1, time_mem=self.time1, time_fp=self.time1,
                 time_fp_stored=self.time1)

    service = ParticipantCountsOverTimeService()
    dao = MetricsLifecycleCacheDao(MetricsCacheType.PUBLIC_METRICS_EXPORT_API)
    service.refresh_data_for_metrics_cache(dao)

    qs = (
          '&stratification=EHR_METRICS'
          '&startDate=2017-12-31'
          '&endDate=2018-01-08'
          )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({u'date': u'2017-12-31',
                   u'metrics': {u'ORGANIZATIONS_ACTIVE': 0, u'EHR_RECEIVED': 0, u'EHR_CONSENTED': 1}},
                  results)
    self.assertIn({u'date': u'2018-01-02',
                   u'metrics': {u'ORGANIZATIONS_ACTIVE': 0, u'EHR_RECEIVED': 0, u'EHR_CONSENTED': 2}},
                  results)
    self.assertIn({u'date': u'2018-01-03',
                   u'metrics': {u'ORGANIZATIONS_ACTIVE': 0, u'EHR_RECEIVED': 0, u'EHR_CONSENTED': 4}},
                  results)
    self.assertIn({u'date': u'2018-01-06',
                   u'metrics': {u'ORGANIZATIONS_ACTIVE': 0, u'EHR_RECEIVED': 0, u'EHR_CONSENTED': 5}},
                  results)

    qs = (
          '&stratification=EHR_METRICS'
          '&startDate=2017-12-31'
          '&endDate=2018-01-08'
          '&awardee=AZ_TUCSON,PITT'
          )

    results = self.send_get('PublicMetrics', query_string=qs)
    self.assertIn({u'date': u'2017-12-31',
                   u'metrics': {u'ORGANIZATIONS_ACTIVE': 0, u'EHR_RECEIVED': 0, u'EHR_CONSENTED': 0}},
                  results)
    self.assertIn({u'date': u'2018-01-02',
                   u'metrics': {u'ORGANIZATIONS_ACTIVE': 0, u'EHR_RECEIVED': 0, u'EHR_CONSENTED': 1}},
                  results)
    self.assertIn({u'date': u'2018-01-03',
                   u'metrics': {u'ORGANIZATIONS_ACTIVE': 0, u'EHR_RECEIVED': 0, u'EHR_CONSENTED': 3}},
                  results)
    self.assertIn({u'date': u'2018-01-06',
                   u'metrics': {u'ORGANIZATIONS_ACTIVE': 0, u'EHR_RECEIVED': 0, u'EHR_CONSENTED': 4}},
                  results)

  def create_demographics_questionnaire(self):
    """Uses the demographics test data questionnaire.  Returns the questionnaire id"""
    return self.create_questionnaire('questionnaire3.json')

  def post_demographics_questionnaire(self,
                                      participant_id,
                                      questionnaire_id,
                                      cabor_signature_string=False,
                                      time=TIME_1, **kwargs):
    """POSTs answers to the demographics questionnaire for the participant"""
    answers = {'code_answers': [],
               'string_answers': [],
               'date_answers': [('dateOfBirth', kwargs.get('dateOfBirth'))]}
    if cabor_signature_string:
      answers['string_answers'].append(('CABoRSignature', kwargs.get('CABoRSignature')))
    else:
      answers['uri_answers'] = [('CABoRSignature', kwargs.get('CABoRSignature'))]

    for link_id in self.code_link_ids:
      if link_id in kwargs:
        if link_id == 'race':
          for race_code in kwargs[link_id]:
            concept = Concept(PPI_SYSTEM, race_code)
            answers['code_answers'].append((link_id, concept))
        else:
          concept = Concept(PPI_SYSTEM, kwargs[link_id])
          answers['code_answers'].append((link_id, concept))

    for link_id in self.string_link_ids:
      code = kwargs.get(link_id)
      answers['string_answers'].append((link_id, code))

    response_data = make_questionnaire_response_json(participant_id, questionnaire_id, **answers)

    with FakeClock(time):
      url = 'Participant/%s/QuestionnaireResponse' % participant_id
      return self.send_post(url, request_data=response_data)
