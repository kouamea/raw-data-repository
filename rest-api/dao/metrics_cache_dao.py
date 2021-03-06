from model.metrics_cache import MetricsEnrollmentStatusCache, MetricsGenderCache, MetricsAgeCache, \
  MetricsRaceCache, MetricsRegionCache, MetricsLifecycleCache, MetricsLanguageCache
from dao.base_dao import BaseDao
from dao.hpo_dao import HPODao
from dao.code_dao import CodeDao
from participant_enums import TEST_HPO_NAME, TEST_EMAIL_PATTERN
from code_constants import PPI_SYSTEM
from census_regions import census_regions
import datetime
import json
from sqlalchemy import func, or_
from participant_enums import Stratifications, AGE_BUCKETS_METRICS_V2_API, \
  AGE_BUCKETS_PUBLIC_METRICS_EXPORT_API, MetricsCacheType

class MetricsEnrollmentStatusCacheDao(BaseDao):
  def __init__(self, cache_type=MetricsCacheType.METRICS_V2_API):
    super(MetricsEnrollmentStatusCacheDao, self).__init__(MetricsEnrollmentStatusCache)
    self.test_hpo_id = HPODao().get_by_name(TEST_HPO_NAME).hpoId
    self.test_email_pattern = TEST_EMAIL_PATTERN
    try:
      self.cache_type = MetricsCacheType(str(cache_type))
    except TypeError:
      raise TypeError("Invalid metrics cache type")

  def get_serving_version_with_session(self, session):
    return (session.query(MetricsEnrollmentStatusCache)
            .order_by(MetricsEnrollmentStatusCache.dateInserted.desc())
            .first())

  def get_active_buckets(self, start_date=None, end_date=None, hpo_ids=None):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is None:
        return None
      last_inserted_date = last_inserted_record.dateInserted

      if self.cache_type == MetricsCacheType.PUBLIC_METRICS_EXPORT_API:
        query = session.query(MetricsEnrollmentStatusCache.date,
                              func.sum(MetricsEnrollmentStatusCache.registeredCount)
                              .label('registeredCount'),
                              func.sum(MetricsEnrollmentStatusCache.consentedCount)
                              .label('consentedCount'),
                              func.sum(MetricsEnrollmentStatusCache.coreCount)
                              .label('coreCount'))

        query = query.filter(MetricsEnrollmentStatusCache.dateInserted == last_inserted_date)
        if start_date:
          query = query.filter(MetricsEnrollmentStatusCache.date >= start_date)
        if end_date:
          query = query.filter(MetricsEnrollmentStatusCache.date <= end_date)

        if hpo_ids:
          query = query.filter(MetricsEnrollmentStatusCache.hpoId.in_(hpo_ids))

        return query.group_by(MetricsEnrollmentStatusCache.date).all()
      else:
        query = session.query(MetricsEnrollmentStatusCache)\
          .filter(MetricsEnrollmentStatusCache.dateInserted == last_inserted_date)
        if start_date:
          query = query.filter(MetricsEnrollmentStatusCache.date >= start_date)
        if end_date:
          query = query.filter(MetricsEnrollmentStatusCache.date <= end_date)

        if hpo_ids:
          query = query.filter(MetricsEnrollmentStatusCache.hpoId.in_(hpo_ids))

        return query.all()

  def get_latest_version_from_cache(self, start_date, end_date, hpo_ids=None):
    buckets = self.get_active_buckets(start_date, end_date, hpo_ids)
    if buckets is None:
      return []
    operation_funcs = {
      MetricsCacheType.PUBLIC_METRICS_EXPORT_API: self.to_public_metrics_client_json,
      MetricsCacheType.METRICS_V2_API: self.to_metrics_client_json
    }
    return operation_funcs[self.cache_type](buckets)

  def delete_old_records(self, n_days_ago=7):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is not None:
        last_date_inserted = last_inserted_record.dateInserted
        seven_days_ago = last_date_inserted - datetime.timedelta(days=n_days_ago)
        delete_sql = """
          delete from metrics_enrollment_status_cache where date_inserted < :seven_days_ago
        """
        params = {'seven_days_ago': seven_days_ago}
        session.execute(delete_sql, params)

  def to_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      new_item = {
        'date': record.date.isoformat(),
        'hpo': record.hpoName,
        'metrics': {
          'registered': record.registeredCount,
          'consented': record.consentedCount,
          'core': record.coreCount
        }
      }
      client_json.append(new_item)
    return client_json

  def to_public_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      new_item = {
        'date': record.date.isoformat(),
        'metrics': {
          'registered': int(record.registeredCount),
          'consented': int(record.consentedCount),
          'core': int(record.coreCount)
        }
      }
      client_json.append(new_item)
    return client_json

  def get_total_interested_count(self, start_date, end_date, hpo_ids=None):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is None:
        return []
      last_inserted_date = last_inserted_record.dateInserted

      if hpo_ids:
        filters_hpo = ' (' + ' OR '.join('hpo_id='+str(x) for x in hpo_ids) + ') AND '
      else:
        filters_hpo = ''
      sql = """
        SELECT (SUM(registered_count) + SUM(consented_count) + SUM(core_count)) AS registered_count,
        date AS start_date
        FROM metrics_enrollment_status_cache
        WHERE %(filters_hpo)s
        date_inserted=:date_inserted
        AND date >= :start_date
        AND date <= :end_date
        GROUP BY date;
      """ % {'filters_hpo': filters_hpo}
      params = {'start_date': start_date, 'end_date': end_date, 'date_inserted': last_inserted_date}

      results_by_date = []

      cursor = session.execute(sql, params)
      try:
        results = cursor.fetchall()
        for result in results:
          date = result[1]
          metrics = {'TOTAL': int(result[0])}
          results_by_date.append({
            'date': str(date),
            'metrics': metrics
          })

      finally:
        cursor.close()

      return results_by_date

  def get_metrics_cache_sql(self):
    sql = """
            insert into metrics_enrollment_status_cache
              SELECT
                :date_inserted AS date_inserted,
                :hpo_id AS hpo_id,
                (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS name,
                c.day AS date,
                IFNULL((
                  SELECT SUM(results.enrollment_count)
                  FROM
                  (
                    SELECT DATE(p.sign_up_time) AS sign_up_time,
                           DATE(ps.enrollment_status_member_time) AS enrollment_status_member_time,
                           DATE(ps.enrollment_status_core_stored_sample_time) AS enrollment_status_core_stored_sample_time,
                           count(*) enrollment_count
                    FROM participant p
                           LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
                    WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
                      AND p.is_ghost_id IS NOT TRUE
                      AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
                      AND p.withdrawal_status = :not_withdraw
                    GROUP BY DATE(p.sign_up_time), DATE(ps.enrollment_status_member_time), DATE(ps.enrollment_status_core_stored_sample_time)
                  ) AS results
                  WHERE c.day>=DATE(sign_up_time) AND (enrollment_status_member_time IS NULL OR c.day < DATE(enrollment_status_member_time))
                ),0) AS registered_count,
                IFNULL((
                  SELECT SUM(results.enrollment_count)
                  FROM
                  (
                    SELECT DATE(p.sign_up_time) AS sign_up_time,
                           DATE(ps.enrollment_status_member_time) AS enrollment_status_member_time,
                           DATE(ps.enrollment_status_core_stored_sample_time) AS enrollment_status_core_stored_sample_time,
                           count(*) enrollment_count
                    FROM participant p
                           LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
                    WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
                      AND p.is_ghost_id IS NOT TRUE
                      AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
                      AND p.withdrawal_status = :not_withdraw
                    GROUP BY DATE(p.sign_up_time), DATE(ps.enrollment_status_member_time), DATE(ps.enrollment_status_core_stored_sample_time)
                  ) AS results
                  WHERE enrollment_status_member_time IS NOT NULL AND day>=DATE(enrollment_status_member_time) AND (enrollment_status_core_stored_sample_time IS NULL OR day < DATE(enrollment_status_core_stored_sample_time))
                ),0) AS consented_count,
                IFNULL((
                  SELECT SUM(results.enrollment_count)
                  FROM
                  (
                    SELECT DATE(p.sign_up_time) AS sign_up_time,
                           DATE(ps.enrollment_status_member_time) AS enrollment_status_member_time,
                           DATE(ps.enrollment_status_core_stored_sample_time) AS enrollment_status_core_stored_sample_time,
                           count(*) enrollment_count
                    FROM participant p
                           LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
                    WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
                      AND p.is_ghost_id IS NOT TRUE
                      AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
                      AND p.withdrawal_status = :not_withdraw
                    GROUP BY DATE(p.sign_up_time), DATE(ps.enrollment_status_member_time), DATE(ps.enrollment_status_core_stored_sample_time)
                  ) AS results
                  WHERE enrollment_status_core_stored_sample_time IS NOT NULL AND day>=DATE(enrollment_status_core_stored_sample_time)
                ),0) AS core_count
              FROM calendar c
              WHERE c.day BETWEEN :start_date AND :end_date
              ;
    """

    return sql

class MetricsGenderCacheDao(BaseDao):
  def __init__(self, cache_type=MetricsCacheType.METRICS_V2_API):
    super(MetricsGenderCacheDao, self).__init__(MetricsGenderCache)
    try:
      self.cache_type = MetricsCacheType(str(cache_type))
    except TypeError:
      raise TypeError("Invalid metrics cache type")

  def get_serving_version_with_session(self, session):
    return (session.query(MetricsGenderCache)
            .order_by(MetricsGenderCache.dateInserted.desc())
            .first())

  def get_active_buckets(self, start_date=None, end_date=None, hpo_ids=None,
                         enrollment_statuses=None):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is None:
        return []
      last_inserted_date = last_inserted_record.dateInserted

      if hpo_ids:
        filters_hpo = ' (' + ' OR '.join('hpo_id=' + str(x) for x in hpo_ids) + ') AND '
      else:
        filters_hpo = ''
      if enrollment_statuses:
        status_filter_list = []
        for status in enrollment_statuses:
          if status == 'INTERESTED':
            status_filter_list.append('registered')
          if status == 'MEMBER':
            status_filter_list.append('consented')
          if status == 'FULL_PARTICIPANT':
            status_filter_list.append('core')
        filters_hpo += ' (' + ' OR '.join('enrollment_status=\'' + str(x)
                                          for x in status_filter_list) + '\') AND '

      if self.cache_type == MetricsCacheType.PUBLIC_METRICS_EXPORT_API:
        sql = """
          SELECT date_inserted, date, CONCAT('{',group_concat(result),'}') AS json_result FROM
          (
            SELECT date_inserted, date, CONCAT('"',gender_name, '":', gender_count) AS result 
            FROM
            (
              SELECT date_inserted, date, gender_name, SUM(gender_count) AS gender_count
              FROM metrics_gender_cache
              WHERE %(filters_hpo)s
              date_inserted=:date_inserted
              AND date BETWEEN :start_date AND :end_date
              GROUP BY date_inserted, date, gender_name
            ) x
          ) a
          GROUP BY date_inserted, date
        """ % {'filters_hpo': filters_hpo}
      else:
        sql = """
          SELECT date_inserted, hpo_id, hpo_name, date, CONCAT('{',group_concat(result),'}') AS json_result FROM
          (
            SELECT date_inserted, hpo_id, hpo_name, date, CONCAT('"',gender_name, '":', gender_count) AS result FROM 
            (
              SELECT date_inserted, hpo_id,hpo_name,date,gender_name, SUM(gender_count) AS gender_count 
              FROM metrics_gender_cache 
              WHERE %(filters_hpo)s
              date_inserted=:date_inserted
              AND date BETWEEN :start_date AND :end_date
              GROUP BY date_inserted, hpo_id, hpo_name, date, gender_name
            ) x
          ) a
          GROUP BY date_inserted, hpo_id, hpo_name, date
        """ % {'filters_hpo': filters_hpo}

      params = {'start_date': start_date, 'end_date': end_date, 'date_inserted': last_inserted_date}

      cursor = session.execute(sql, params)
      try:
        results = cursor.fetchall()
      finally:
        cursor.close()

      return results

  def get_latest_version_from_cache(self, start_date, end_date, hpo_ids=None,
                                    enrollment_statuses=None):
    buckets = self.get_active_buckets(start_date, end_date, hpo_ids, enrollment_statuses)
    if buckets is None:
      return []
    operation_funcs = {
      MetricsCacheType.PUBLIC_METRICS_EXPORT_API: self.to_public_metrics_client_json,
      MetricsCacheType.METRICS_V2_API: self.to_metrics_client_json
    }
    return operation_funcs[self.cache_type](buckets)

  def delete_old_records(self, n_days_ago=7):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is not None:
        last_date_inserted = last_inserted_record.dateInserted
        seven_days_ago = last_date_inserted - datetime.timedelta(days=n_days_ago)
        delete_sql = """
          delete from metrics_gender_cache where date_inserted < :seven_days_ago
        """
        params = {'seven_days_ago': seven_days_ago}
        session.execute(delete_sql, params)

  def to_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      new_item = {
        'date': record.date.isoformat(),
        'hpo': record.hpo_name,
        'metrics': json.loads(record.json_result)
      }
      if 'UNMAPPED' not in new_item['metrics']:
        new_item['metrics']['UNMAPPED'] = 0
      client_json.append(new_item)
    return client_json

  def to_public_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      new_item = {
        'date': record.date.isoformat(),
        'metrics': json.loads(record.json_result)
      }
      if 'UNMAPPED' not in new_item['metrics']:
        new_item['metrics']['UNMAPPED'] = 0
      client_json.append(new_item)
    return client_json

  def get_metrics_cache_sql(self):

    gender_code_dict = {
      'GenderIdentity_Woman': 354,
      'GenderIdentity_Man': 356,
      'GenderIdentity_Transgender': 355,
      'PMI_Skip': 930,
      'GenderIdentity_NonBinary': 358,
      'GenderIdentity_AdditionalOptions': 357,
      'PMI_PreferNotToAnswer': 924
    }

    for k in gender_code_dict:
      code = CodeDao().get_code(PPI_SYSTEM, k)
      if code is not None:
        gender_code_dict[k] = code.codeId

    sql = """insert into metrics_gender_cache """
    gender_names = ['UNSET', 'Woman', 'Man', 'Transgender', 'PMI_Skip', 'Non-Binary',
                    'Other/Additional Options', 'Prefer not to say']
    gender_conditions = [
      ' ps.gender_identity_id IS NULL ',
      ' ps.gender_identity_id=' + str(gender_code_dict['GenderIdentity_Woman']) + ' ',
      ' ps.gender_identity_id=' + str(gender_code_dict['GenderIdentity_Man']) + ' ',
      ' ps.gender_identity_id=' + str(gender_code_dict['GenderIdentity_Transgender']) + ' ',
      ' ps.gender_identity_id=' + str(gender_code_dict['PMI_Skip']) + ' ',
      ' ps.gender_identity_id=' + str(gender_code_dict['GenderIdentity_NonBinary']) + ' ',
      ' ps.gender_identity_id=' + str(gender_code_dict['GenderIdentity_AdditionalOptions']) + ' ',
      ' ps.gender_identity_id=' + str(gender_code_dict['PMI_PreferNotToAnswer']) + ' ',
    ]
    sub_queries = []
    sql_template = """
      SELECT
        :date_inserted AS date_inserted,
        'core' as enrollment_status,
        :hpo_id AS hpo_id,
        (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
        c.day AS date,
        '{gender_name}' AS gender_name,  
        IFNULL((
          SELECT SUM(results.gender_count)
          FROM
          (
            SELECT DATE(p.sign_up_time) as day,
                   DATE(ps.enrollment_status_core_stored_sample_time) as enrollment_status_core_stored_sample_time,
                   COUNT(*) gender_count
            FROM participant p
                   LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
            WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
              AND p.is_ghost_id IS NOT TRUE
              AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
              AND p.withdrawal_status = :not_withdraw
              AND {gender_condition}
            GROUP BY DATE(p.sign_up_time), DATE(ps.enrollment_status_core_stored_sample_time)
          ) AS results
          WHERE results.day <= c.day
          AND enrollment_status_core_stored_sample_time IS NOT NULL
          AND DATE(enrollment_status_core_stored_sample_time) <= c.day
        ),0) AS gender_count
      FROM calendar c
      WHERE c.day BETWEEN :start_date AND :end_date
      UNION
      SELECT
        :date_inserted AS date_inserted,
        'registered' as enrollment_status,
        :hpo_id AS hpo_id,
        (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
        c.day AS date,
        '{gender_name}' AS gender_name,  
        IFNULL((
          SELECT SUM(results.gender_count)
          FROM
          (
            SELECT DATE(p.sign_up_time) as day,
                   DATE(ps.enrollment_status_member_time) as enrollment_status_member_time,
                   COUNT(*) gender_count
            FROM participant p
                   LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
            WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
              AND p.is_ghost_id IS NOT TRUE
              AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
              AND p.withdrawal_status = :not_withdraw
              AND {gender_condition}
            GROUP BY DATE(p.sign_up_time), DATE(ps.enrollment_status_member_time)
          ) AS results
          WHERE results.day <= c.day
          AND (enrollment_status_member_time is null or DATE(enrollment_status_member_time)>c.day)
        ),0) AS gender_count
      FROM calendar c
      WHERE c.day BETWEEN :start_date AND :end_date
      UNION
      SELECT
        :date_inserted AS date_inserted,
        'consented' as enrollment_status,
        :hpo_id AS hpo_id,
        (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
        c.day AS date,
        '{gender_name}' AS gender_name,  
        IFNULL((
          SELECT SUM(results.gender_count)
          FROM
          (
            SELECT DATE(p.sign_up_time) as day,
                   DATE(ps.enrollment_status_member_time) as enrollment_status_member_time,
                   DATE(ps.enrollment_status_core_stored_sample_time) as enrollment_status_core_stored_sample_time,
                   COUNT(*) gender_count
            FROM participant p
                   LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
            WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
              AND p.is_ghost_id IS NOT TRUE
              AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
              AND p.withdrawal_status = :not_withdraw
              AND {gender_condition}
            GROUP BY DATE(p.sign_up_time), DATE(ps.enrollment_status_member_time), DATE(ps.enrollment_status_core_stored_sample_time)
          ) AS results
          WHERE results.day <= c.day
          AND enrollment_status_member_time IS NOT NULL
          AND DATE(enrollment_status_member_time) <= c.day
          AND (enrollment_status_core_stored_sample_time is null or DATE(enrollment_status_core_stored_sample_time)>c.day)
        ),0) AS gender_count
      FROM calendar c
      WHERE c.day BETWEEN :start_date AND :end_date
    """
    for gender_name, gender_condition in zip(gender_names, gender_conditions):
      sub_query = sql_template.format(gender_name=gender_name, gender_condition=gender_condition)
      sub_queries.append(sub_query)

    sql += ' union '.join(sub_queries)

    return sql

class MetricsAgeCacheDao(BaseDao):

  def __init__(self, cache_type=MetricsCacheType.METRICS_V2_API):
    super(MetricsAgeCacheDao, self).__init__(MetricsAgeCache)
    try:
      self.cache_type = MetricsCacheType(str(cache_type))
    except TypeError:
      raise TypeError("Invalid metrics cache type")

    if cache_type == MetricsCacheType.PUBLIC_METRICS_EXPORT_API:
      self.age_ranges = AGE_BUCKETS_PUBLIC_METRICS_EXPORT_API
    else:
      self.age_ranges = AGE_BUCKETS_METRICS_V2_API

  def get_serving_version_with_session(self, session):
    return (session.query(MetricsAgeCache)
            .filter(MetricsAgeCache.type == str(self.cache_type))
            .order_by(MetricsAgeCache.dateInserted.desc())
            .first())

  def get_active_buckets(self, start_date=None, end_date=None, hpo_ids=None,
                         enrollment_statuses=None):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is None:
        return []
      last_inserted_date = last_inserted_record.dateInserted

      if hpo_ids:
        filters_hpo = ' (' + ' OR '.join('hpo_id='+str(x) for x in hpo_ids) + ') AND '
      else:
        filters_hpo = ''
      if enrollment_statuses:
        status_filter_list = []
        for status in enrollment_statuses:
          if status == 'INTERESTED':
            status_filter_list.append('registered')
          if status == 'MEMBER':
            status_filter_list.append('consented')
          if status == 'FULL_PARTICIPANT':
            status_filter_list.append('core')
        filters_hpo += ' (' + ' OR '.join('enrollment_status=\'' + str(x)
                                          for x in status_filter_list) + '\') AND '

      if self.cache_type == MetricsCacheType.PUBLIC_METRICS_EXPORT_API:
        sql = """
          SELECT date_inserted, date, CONCAT('{',group_concat(result),'}') AS json_result FROM
          (
            SELECT date_inserted, date, CONCAT('"',age_range, '":', age_count) AS result
            FROM
            (
              select date_inserted, date, age_range, SUM(age_count) AS age_count
              FROM metrics_age_cache
              WHERE %(filters_hpo)s
              date_inserted=:date_inserted
              AND date BETWEEN :start_date AND :end_date
              AND type=:cache_type
              GROUP BY date_inserted, date, age_range
            ) x
          ) a
          GROUP BY date_inserted, date
        """ % {'filters_hpo': filters_hpo}
      else:
        sql = """
          SELECT date_inserted, hpo_id, hpo_name, date, CONCAT('{',group_concat(result),'}') AS json_result FROM
          (
            SELECT date_inserted, hpo_id, hpo_name, date, CONCAT('"',age_range, '":', age_count) AS result FROM 
            (
              SELECT date_inserted, hpo_id, hpo_name, date, age_range, SUM(age_count) as age_count
              FROM metrics_age_cache
              WHERE %(filters_hpo)s
              date_inserted=:date_inserted
              AND date BETWEEN :start_date AND :end_date
              AND type=:cache_type
              GROUP BY date_inserted, hpo_id, hpo_name, date, age_range
            ) x
          ) a
          GROUP BY date_inserted, hpo_id, hpo_name, date
        """ % {'filters_hpo': filters_hpo}

      params = {'start_date': start_date, 'end_date': end_date, 'date_inserted': last_inserted_date,
                'cache_type': str(self.cache_type)}

      cursor = session.execute(sql, params)
      try:
        results = cursor.fetchall()
      finally:
        cursor.close()

      return results

  def get_latest_version_from_cache(self, start_date, end_date, hpo_ids=None,
                                    enrollment_statuses=None):
    buckets = self.get_active_buckets(start_date, end_date, hpo_ids, enrollment_statuses)
    if buckets is None:
      return []
    operation_funcs = {
      MetricsCacheType.PUBLIC_METRICS_EXPORT_API: self.to_public_metrics_client_json,
      MetricsCacheType.METRICS_V2_API: self.to_metrics_client_json
    }
    return operation_funcs[self.cache_type](buckets)

  def delete_old_records(self, n_days_ago=7):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is not None:
        last_date_inserted = last_inserted_record.dateInserted
        seven_days_ago = last_date_inserted - datetime.timedelta(days=n_days_ago)
        delete_sql = """
          delete from metrics_age_cache where date_inserted < :seven_days_ago
        """
        params = {'seven_days_ago': seven_days_ago}
        session.execute(delete_sql, params)

  def to_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      new_item = {
        'date': record.date.isoformat(),
        'hpo': record.hpo_name,
        'metrics': json.loads(record.json_result)
      }
      client_json.append(new_item)
    return client_json

  def to_public_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      new_item = {
        'date': record.date.isoformat(),
        'metrics': json.loads(record.json_result)
      }
      client_json.append(new_item)
    return client_json

  def get_metrics_cache_sql(self):
    sql = """
      insert into metrics_age_cache 
        SELECT
          :date_inserted AS date_inserted,
          'core' as enrollment_status,
          '{cache_type}' as type,
          :hpo_id AS hpo_id,
          (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
          c.day AS date,
          'UNSET' AS age_range,
          IFNULL((
            SELECT SUM(results.age_count)
            FROM
            (
              SELECT DATE(p.sign_up_time) AS day,
                     DATE(ps.enrollment_status_core_stored_sample_time) as enrollment_status_core_stored_sample_time,
                     count(*) age_count
              FROM participant p
                     LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
              WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
                AND p.is_ghost_id IS NOT TRUE
                AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
                AND p.withdrawal_status = :not_withdraw
                AND ps.date_of_birth IS NULL
              GROUP BY DATE(p.sign_up_time), DATE(ps.enrollment_status_core_stored_sample_time)
            ) AS results
            WHERE results.day <= c.day
            AND enrollment_status_core_stored_sample_time IS NOT NULL
            AND DATE(enrollment_status_core_stored_sample_time) <= c.day
          ),0) AS age_count
        FROM calendar c
        WHERE c.day BETWEEN :start_date AND :end_date
        UNION
        SELECT
          :date_inserted AS date_inserted,
          'registered' as enrollment_status,
          '{cache_type}' as type,
          :hpo_id AS hpo_id,
          (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
          c.day AS date,
          'UNSET' AS age_range,
          IFNULL((
            SELECT SUM(results.age_count)
            FROM
            (
              SELECT DATE(p.sign_up_time) AS day,
                     DATE(ps.enrollment_status_member_time) as enrollment_status_member_time,
                     count(*) age_count
              FROM participant p
                     LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
              WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
                AND p.is_ghost_id IS NOT TRUE
                AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
                AND p.withdrawal_status = :not_withdraw
                AND ps.date_of_birth IS NULL
              GROUP BY DATE(p.sign_up_time), DATE(ps.enrollment_status_member_time)
            ) AS results
            WHERE results.day <= c.day
            AND (enrollment_status_member_time is null or DATE(enrollment_status_member_time)>c.day)
          ),0) AS age_count
        FROM calendar c
        WHERE c.day BETWEEN :start_date AND :end_date
        UNION
        SELECT
          :date_inserted AS date_inserted,
          'consented' as enrollment_status,
          '{cache_type}' as type,
          :hpo_id AS hpo_id,
          (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
          c.day AS date,
          'UNSET' AS age_range,
          IFNULL((
            SELECT SUM(results.age_count)
            FROM
            (
              SELECT DATE(p.sign_up_time) AS day,
                     DATE(ps.enrollment_status_member_time) as enrollment_status_member_time,
                     DATE(ps.enrollment_status_core_stored_sample_time) as enrollment_status_core_stored_sample_time,
                     count(*) age_count
              FROM participant p
                     LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
              WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
                AND p.is_ghost_id IS NOT TRUE
                AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
                AND p.withdrawal_status = :not_withdraw
                AND ps.date_of_birth IS NULL
              GROUP BY DATE(p.sign_up_time), DATE(ps.enrollment_status_member_time), DATE(ps.enrollment_status_core_stored_sample_time)
            ) AS results
            WHERE results.day <= c.day
            AND enrollment_status_member_time IS NOT NULL
            AND DATE(enrollment_status_member_time) <= c.day
            AND (enrollment_status_core_stored_sample_time is null or DATE(enrollment_status_core_stored_sample_time)>c.day)
          ),0) AS age_count
        FROM calendar c
        WHERE c.day BETWEEN :start_date AND :end_date
        UNION
    """.format(cache_type=str(self.cache_type))

    age_ranges_conditions = []
    for age_range in self.age_ranges:
      age_borders = filter(None, age_range.split('-'))
      if len(age_borders) == 2:
        age_ranges_conditions.append(' AND (Date_format(From_Days(To_Days(c.day) - To_Days(dob)), '
                                     '\'%Y\') + 0) BETWEEN ' + age_borders[0] + ' AND '
                                     + age_borders[1],)
      else:
        age_ranges_conditions.append(' AND (Date_format(From_Days(To_Days(c.day) - To_Days(dob)), '
                                     '\'%Y\') + 0) >= ' + age_borders[0])

    sub_queries = []
    sql_template = """
      SELECT
        :date_inserted AS date_inserted,
        'core' as enrollment_status,
        '{cache_type}' as type,
        :hpo_id AS hpo_id,
        (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
        c.day as date,
        '{age_range}' AS age_range,
        IFNULL((
          SELECT SUM(results.age_count)
          FROM
          (
            SELECT DATE(p.sign_up_time) AS day,
                   DATE(ps.date_of_birth) AS dob,
                   DATE(ps.enrollment_status_core_stored_sample_time) as enrollment_status_core_stored_sample_time,
                   count(*) age_count
            FROM participant p
                   LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
            WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
              AND p.is_ghost_id IS NOT TRUE
              AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
              AND p.withdrawal_status = :not_withdraw
              AND ps.date_of_birth IS NOT NULL
            GROUP BY DATE(p.sign_up_time), DATE(ps.date_of_birth), DATE(ps.enrollment_status_core_stored_sample_time)
          ) AS results
          WHERE results.day <= c.day 
          AND enrollment_status_core_stored_sample_time IS NOT NULL
          AND DATE(enrollment_status_core_stored_sample_time) <= c.day
          {age_range_condition}
        ),0) AS age_count
      FROM calendar c
      WHERE c.day BETWEEN :start_date AND :end_date
      UNION
      SELECT
        :date_inserted AS date_inserted,
        'registered' as enrollment_status,
        '{cache_type}' as type,
        :hpo_id AS hpo_id,
        (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
        c.day as date,
        '{age_range}' AS age_range,
        IFNULL((
          SELECT SUM(results.age_count)
          FROM
          (
            SELECT DATE(p.sign_up_time) AS day,
                   DATE(ps.date_of_birth) AS dob,
                   DATE(ps.enrollment_status_member_time) as enrollment_status_member_time,
                   count(*) age_count
            FROM participant p
                   LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
            WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
              AND p.is_ghost_id IS NOT TRUE
              AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
              AND p.withdrawal_status = :not_withdraw
              AND ps.date_of_birth IS NOT NULL
            GROUP BY DATE(p.sign_up_time), DATE(ps.date_of_birth), DATE(ps.enrollment_status_member_time)
          ) AS results
          WHERE results.day <= c.day 
          AND (enrollment_status_member_time is null or DATE(enrollment_status_member_time)>c.day)
          {age_range_condition}
        ),0) AS age_count
      FROM calendar c
      WHERE c.day BETWEEN :start_date AND :end_date
      UNION
      SELECT
        :date_inserted AS date_inserted,
        'consented' as enrollment_status,
        '{cache_type}' as type,
        :hpo_id AS hpo_id,
        (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
        c.day as date,
        '{age_range}' AS age_range,
        IFNULL((
          SELECT SUM(results.age_count)
          FROM
          (
            SELECT DATE(p.sign_up_time) AS day,
                   DATE(ps.date_of_birth) AS dob,
                   DATE(ps.enrollment_status_member_time) as enrollment_status_member_time,
                   DATE(ps.enrollment_status_core_stored_sample_time) as enrollment_status_core_stored_sample_time,
                   count(*) age_count
            FROM participant p
                   LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
            WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
              AND p.is_ghost_id IS NOT TRUE
              AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
              AND p.withdrawal_status = :not_withdraw
              AND ps.date_of_birth IS NOT NULL
            GROUP BY DATE(p.sign_up_time), DATE(ps.date_of_birth), DATE(ps.enrollment_status_member_time), DATE(ps.enrollment_status_core_stored_sample_time)
          ) AS results
          WHERE results.day <= c.day 
          AND enrollment_status_member_time IS NOT NULL
          AND DATE(enrollment_status_member_time) <= c.day
          AND (enrollment_status_core_stored_sample_time is null or DATE(enrollment_status_core_stored_sample_time)>c.day)
          {age_range_condition}
        ),0) AS age_count
      FROM calendar c
      WHERE c.day BETWEEN :start_date AND :end_date
    """

    for age_range, age_range_condition in zip(self.age_ranges, age_ranges_conditions):
      sub_query = sql_template.format(cache_type=str(self.cache_type),
                                      age_range=age_range,
                                      age_range_condition=age_range_condition)
      sub_queries.append(sub_query)

    sql += ' union '.join(sub_queries)

    return sql

class MetricsRaceCacheDao(BaseDao):

  def __init__(self, cache_type=MetricsCacheType.METRICS_V2_API):
    super(MetricsRaceCacheDao, self).__init__(MetricsRaceCache)
    try:
      self.cache_type = MetricsCacheType(str(cache_type))
    except TypeError:
      raise TypeError("Invalid metrics cache type")

  def get_serving_version_with_session(self, session):
    return (session.query(MetricsRaceCache)
            .order_by(MetricsRaceCache.dateInserted.desc())
            .first())

  def get_active_buckets(self, start_date=None, end_date=None, hpo_ids=None,
                         enrollment_statuses=None):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is None:
        return None
      last_inserted_date = last_inserted_record.dateInserted
      if self.cache_type == MetricsCacheType.PUBLIC_METRICS_EXPORT_API:
        query = session.query(MetricsRaceCache.date,
                              func.sum(MetricsRaceCache.americanIndianAlaskaNative)
                              .label('americanIndianAlaskaNative'),
                              func.sum(MetricsRaceCache.asian)
                              .label('asian'),
                              func.sum(MetricsRaceCache.blackAfricanAmerican)
                              .label('blackAfricanAmerican'),
                              func.sum(MetricsRaceCache.middleEasternNorthAfrican)
                              .label('middleEasternNorthAfrican'),
                              func.sum(MetricsRaceCache.nativeHawaiianOtherPacificIslander)
                              .label('nativeHawaiianOtherPacificIslander'),
                              func.sum(MetricsRaceCache.white)
                              .label('white'),
                              func.sum(MetricsRaceCache.hispanicLatinoSpanish)
                              .label('hispanicLatinoSpanish'),
                              func.sum(MetricsRaceCache.noneOfTheseFullyDescribeMe)
                              .label('noneOfTheseFullyDescribeMe'),
                              func.sum(MetricsRaceCache.preferNotToAnswer)
                              .label('preferNotToAnswer'),
                              func.sum(MetricsRaceCache.multiAncestry)
                              .label('multiAncestry'),
                              func.sum(MetricsRaceCache.noAncestryChecked)
                              .label('noAncestryChecked')
                              )
        query = query.filter(MetricsRaceCache.dateInserted == last_inserted_date)

        if start_date:
          query = query.filter(MetricsRaceCache.date >= start_date)
        if end_date:
          query = query.filter(MetricsRaceCache.date <= end_date)
        if hpo_ids:
          query = query.filter(MetricsRaceCache.hpoId.in_(hpo_ids))
        if enrollment_statuses:
          param_list = []
          for status in enrollment_statuses:
            if status == 'INTERESTED':
              param_list.append(MetricsRaceCache.registeredFlag == 1)
            elif status == 'MEMBER':
              param_list.append(MetricsRaceCache.consentedFlag == 1)
            elif status == 'FULL_PARTICIPANT':
              param_list.append(MetricsRaceCache.coreFlag == 1)
          if param_list:
            query = query.filter(or_(*param_list))

        return query.group_by(MetricsRaceCache.date).all()
      else:
        query = session.query(MetricsRaceCache)\
          .filter(MetricsRaceCache.dateInserted == last_inserted_date)
        if start_date:
          query = query.filter(MetricsRaceCache.date >= start_date)
        if end_date:
          query = query.filter(MetricsRaceCache.date <= end_date)
        if hpo_ids:
          query = query.filter(MetricsRaceCache.hpoId.in_(hpo_ids))
        if enrollment_statuses:
          param_list = []
          for status in enrollment_statuses:
            if status == 'INTERESTED':
              param_list.append(MetricsRaceCache.registeredFlag == 1)
            elif status == 'MEMBER':
              param_list.append(MetricsRaceCache.consentedFlag == 1)
            elif status == 'FULL_PARTICIPANT':
              param_list.append(MetricsRaceCache.coreFlag == 1)
          if param_list:
            query = query.filter(or_(*param_list))

        return query.all()

  def get_latest_version_from_cache(self, start_date, end_date, hpo_ids=None,
                                    enrollment_statuses=None):
    buckets = self.get_active_buckets(start_date, end_date, hpo_ids, enrollment_statuses)
    if buckets is None:
      return []
    operation_funcs = {
      MetricsCacheType.PUBLIC_METRICS_EXPORT_API: self.to_public_metrics_client_json,
      MetricsCacheType.METRICS_V2_API: self.to_metrics_client_json
    }
    return operation_funcs[self.cache_type](buckets)

  def delete_old_records(self, n_days_ago=7):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is not None:
        last_date_inserted = last_inserted_record.dateInserted
        seven_days_ago = last_date_inserted - datetime.timedelta(days=n_days_ago)
        delete_sql = """
          delete from metrics_race_cache where date_inserted < :seven_days_ago
        """
        params = {'seven_days_ago': seven_days_ago}
        session.execute(delete_sql, params)

  def to_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      new_item = {
        'date': record.date.isoformat(),
        'hpo': record.hpoName,
        'metrics': {
          'American_Indian_Alaska_Native': record.americanIndianAlaskaNative,
          'Asian': record.asian,
          'Black_African_American': record.blackAfricanAmerican,
          'Middle_Eastern_North_African': record.middleEasternNorthAfrican,
          'Native_Hawaiian_other_Pacific_Islander': record.nativeHawaiianOtherPacificIslander,
          'White': record.white,
          'Hispanic_Latino_Spanish': record.hispanicLatinoSpanish,
          'None_Of_These_Fully_Describe_Me': record.noneOfTheseFullyDescribeMe,
          'Prefer_Not_To_Answer': record.preferNotToAnswer,
          'Multi_Ancestry': record.multiAncestry,
          'No_Ancestry_Checked': record.noAncestryChecked
        }
      }
      client_json.append(new_item)
    return client_json

  def to_public_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      new_item = {
        'date': record.date.isoformat(),
        'metrics': {
          'American_Indian_Alaska_Native': int(record.americanIndianAlaskaNative),
          'Asian': int(record.asian),
          'Black_African_American': int(record.blackAfricanAmerican),
          'Middle_Eastern_North_African': int(record.middleEasternNorthAfrican),
          'Native_Hawaiian_other_Pacific_Islander': int(record.nativeHawaiianOtherPacificIslander),
          'White': int(record.white),
          'Hispanic_Latino_Spanish': int(record.hispanicLatinoSpanish),
          'None_Of_These_Fully_Describe_Me': int(record.noneOfTheseFullyDescribeMe),
          'Prefer_Not_To_Answer': int(record.preferNotToAnswer),
          'Multi_Ancestry': int(record.multiAncestry),
          'No_Ancestry_Checked': int(record.noAncestryChecked)
        }
      }
      client_json.append(new_item)
    return client_json

  def get_metrics_cache_sql(self):

    race_code_dict = {
      'Race_WhatRaceEthnicity': 193,
      'WhatRaceEthnicity_Hispanic': 207,
      'WhatRaceEthnicity_Black': 259,
      'WhatRaceEthnicity_White': 220,
      'WhatRaceEthnicity_AIAN': 252,
      'WhatRaceEthnicity_RaceEthnicityNoneOfThese': 235,
      'WhatRaceEthnicity_Asian': 194,
      'PMI_PreferNotToAnswer': 924,
      'WhatRaceEthnicity_MENA': 274,
      'PMI_Skip': 930,
      'WhatRaceEthnicity_NHPI': 237
    }

    for k in race_code_dict:
      code = CodeDao().get_code(PPI_SYSTEM, k)
      if code is not None:
        race_code_dict[k] = code.codeId

    sql = """
          insert into metrics_race_cache
            SELECT
              :date_inserted as date_inserted,
              registered as registered_flag,
              consented as consented_flag,
              core as core_flag,
              hpo_id,
              (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
              day,
              SUM(American_Indian_Alaska_Native) AS American_Indian_Alaska_Native,
              SUM(Asian) AS Asian,
              SUM(Black_African_American) AS Black_African_American,
              SUM(Middle_Eastern_North_African) AS Middle_Eastern_North_African,
              SUM(Native_Hawaiian_other_Pacific_Islander) AS Native_Hawaiian_other_Pacific_Islander,
              SUM(White) AS White,
              SUM(Hispanic_Latino_Spanish) AS Hispanic_Latino_Spanish,
              SUM(None_Of_These_Fully_Describe_Me) AS None_Of_These_Fully_Describe_Me,
              SUM(Prefer_Not_To_Answer) AS Prefer_Not_To_Answer,
              SUM(Multi_Ancestry) AS Multi_Ancestry,
              SUM(No_Ancestry_Checked) AS No_Ancestry_Checked
              FROM
              (
                SELECT p.hpo_id,
                       day,
                       CASE WHEN enrollment_status_member_time IS NULL OR DATE(enrollment_status_member_time)>calendar.day
                           THEN 1 ELSE 0 END AS registered,
                       CASE WHEN (enrollment_status_member_time IS NOT NULL AND DATE(enrollment_status_member_time)<=calendar.day) AND
                                 (enrollment_status_core_stored_sample_time IS NULL OR DATE(enrollment_status_core_stored_sample_time)>calendar.day)
                           THEN 1 ELSE 0 END AS consented,
                       CASE WHEN enrollment_status_core_stored_sample_time IS NOT NULL AND DATE(enrollment_status_core_stored_sample_time)<=calendar.day
                           THEN 1 ELSE 0 END AS core,
                       CASE WHEN WhatRaceEthnicity_AIAN=1 AND Number_of_Answer=1 THEN 1 ELSE 0 END AS American_Indian_Alaska_Native,
                       CASE WHEN WhatRaceEthnicity_Asian=1 AND Number_of_Answer=1 THEN 1 ELSE 0 END AS Asian,
                       CASE WHEN WhatRaceEthnicity_Black=1 AND Number_of_Answer=1 THEN 1 ELSE 0 END AS Black_African_American,
                       CASE WHEN WhatRaceEthnicity_MENA=1 AND Number_of_Answer=1 THEN 1 ELSE 0 END AS Middle_Eastern_North_African,
                       CASE WHEN WhatRaceEthnicity_NHPI=1 AND Number_of_Answer=1 THEN 1 ELSE 0 END AS Native_Hawaiian_other_Pacific_Islander,
                       CASE WHEN WhatRaceEthnicity_White=1 AND Number_of_Answer=1 THEN 1 ELSE 0 END AS White,
                       CASE WHEN WhatRaceEthnicity_Hispanic=1 AND Number_of_Answer=1 THEN 1 ELSE 0 END AS Hispanic_Latino_Spanish,
                       CASE WHEN WhatRaceEthnicity_RaceEthnicityNoneOfThese=1 AND Number_of_Answer=1 THEN 1 ELSE 0 END AS None_Of_These_Fully_Describe_Me,
                       CASE WHEN PMI_PreferNotToAnswer=1 AND Number_of_Answer=1 THEN 1 ELSE 0 END AS Prefer_Not_To_Answer,
                       CASE
                         WHEN (WhatRaceEthnicity_Hispanic + WhatRaceEthnicity_Black + WhatRaceEthnicity_White + WhatRaceEthnicity_AIAN + WhatRaceEthnicity_Asian + WhatRaceEthnicity_MENA + WhatRaceEthnicity_NHPI) >
                              1
                           THEN 1
                         ELSE 0
                       END AS Multi_Ancestry,
                       CASE
                         WHEN (PMI_Skip = 1 AND Number_of_Answer=1) OR UNSET = 1
                           THEN 1
                         ELSE 0
                       END AS No_Ancestry_Checked
                FROM (
                       SELECT participant_id,
                              hpo_id,
                              sign_up_time,
                              enrollment_status_member_time,
                              enrollment_status_core_stored_sample_time,
                              MAX(WhatRaceEthnicity_Hispanic)                 AS WhatRaceEthnicity_Hispanic,
                              MAX(WhatRaceEthnicity_Black)                    AS WhatRaceEthnicity_Black,
                              MAX(WhatRaceEthnicity_White)                    AS WhatRaceEthnicity_White,
                              MAX(WhatRaceEthnicity_AIAN)                     AS WhatRaceEthnicity_AIAN,
                              MAX(UNSET)                                      AS UNSET,
                              MAX(WhatRaceEthnicity_RaceEthnicityNoneOfThese) AS WhatRaceEthnicity_RaceEthnicityNoneOfThese,
                              MAX(WhatRaceEthnicity_Asian)                    AS WhatRaceEthnicity_Asian,
                              MAX(PMI_PreferNotToAnswer)                      AS PMI_PreferNotToAnswer,
                              MAX(WhatRaceEthnicity_MENA)                     AS WhatRaceEthnicity_MENA,
                              MAX(PMI_Skip)                                   AS PMI_Skip,
                              MAX(WhatRaceEthnicity_NHPI)                     AS WhatRaceEthnicity_NHPI,
                              COUNT(*) as Number_of_Answer
                       FROM (
                              SELECT p.participant_id,
                                     p.hpo_id,
                                     p.sign_up_time,
                                     ps.enrollment_status_member_time,
                                     ps.enrollment_status_core_stored_sample_time,
                                     CASE WHEN q.code_id = {WhatRaceEthnicity_Hispanic} THEN 1 ELSE 0 END   AS WhatRaceEthnicity_Hispanic,
                                     CASE WHEN q.code_id = {WhatRaceEthnicity_Black} THEN 1 ELSE 0 END   AS WhatRaceEthnicity_Black,
                                     CASE WHEN q.code_id = {WhatRaceEthnicity_White} THEN 1 ELSE 0 END   AS WhatRaceEthnicity_White,
                                     CASE WHEN q.code_id = {WhatRaceEthnicity_AIAN} THEN 1 ELSE 0 END   AS WhatRaceEthnicity_AIAN,
                                     CASE WHEN q.code_id IS NULL THEN 1 ELSE 0 END AS UNSET,
                                     CASE WHEN q.code_id = {WhatRaceEthnicity_RaceEthnicityNoneOfThese} THEN 1 ELSE 0 END   AS WhatRaceEthnicity_RaceEthnicityNoneOfThese,
                                     CASE WHEN q.code_id = {WhatRaceEthnicity_Asian} THEN 1 ELSE 0 END   AS WhatRaceEthnicity_Asian,
                                     CASE WHEN q.code_id = {PMI_PreferNotToAnswer} THEN 1 ELSE 0 END   AS PMI_PreferNotToAnswer,
                                     CASE WHEN q.code_id = {WhatRaceEthnicity_MENA} THEN 1 ELSE 0 END   AS WhatRaceEthnicity_MENA,
                                     CASE WHEN q.code_id = {PMI_Skip} THEN 1 ELSE 0 END   AS PMI_Skip,
                                     CASE WHEN q.code_id = {WhatRaceEthnicity_NHPI} THEN 1 ELSE 0 END   AS WhatRaceEthnicity_NHPI
                              FROM participant p
                                     INNER JOIN participant_summary ps ON p.participant_id = ps.participant_id
                                     LEFT JOIN
                                   (
                                     SELECT qr.participant_id, qra.value_code_id as code_id
                                     FROM questionnaire_question qq,
                                          questionnaire_response_answer qra,
                                          questionnaire_response qr
                                     WHERE qq.questionnaire_question_id = qra.question_id
                                       AND qq.code_id = {Race_WhatRaceEthnicity}
                                       AND qra.questionnaire_response_id = qr.questionnaire_response_id
                                   ) q ON p.participant_id = q.participant_id
                              WHERE p.hpo_id=:hpo_id AND p.hpo_id <> :test_hpo_id
                                AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
                                AND p.withdrawal_status = :not_withdraw
                                AND p.is_ghost_id IS NOT TRUE
                                AND ps.questionnaire_on_the_basics = 1
                            ) x
                       GROUP BY participant_id, hpo_id, sign_up_time, enrollment_status_member_time, enrollment_status_core_stored_sample_time
                     ) p,
                     calendar
                WHERE calendar.day >= :start_date
                  AND calendar.day <= :end_date
                  AND calendar.day >= Date(p.sign_up_time)
              ) y
              GROUP BY day, hpo_id, registered, consented, core
              ;
        """.format(Race_WhatRaceEthnicity=race_code_dict['Race_WhatRaceEthnicity'],
                   WhatRaceEthnicity_Hispanic=race_code_dict['WhatRaceEthnicity_Hispanic'],
                   WhatRaceEthnicity_Black=race_code_dict['WhatRaceEthnicity_Black'],
                   WhatRaceEthnicity_White=race_code_dict['WhatRaceEthnicity_White'],
                   WhatRaceEthnicity_AIAN=race_code_dict['WhatRaceEthnicity_AIAN'],
                   WhatRaceEthnicity_RaceEthnicityNoneOfThese=
                             race_code_dict['WhatRaceEthnicity_RaceEthnicityNoneOfThese'],
                   WhatRaceEthnicity_Asian=race_code_dict['WhatRaceEthnicity_Asian'],
                   PMI_PreferNotToAnswer=race_code_dict['PMI_PreferNotToAnswer'],
                   WhatRaceEthnicity_MENA=race_code_dict['WhatRaceEthnicity_MENA'],
                   PMI_Skip=race_code_dict['PMI_Skip'],
                   WhatRaceEthnicity_NHPI=race_code_dict['WhatRaceEthnicity_NHPI'])
    return sql

class MetricsRegionCacheDao(BaseDao):

  def __init__(self, cache_type=MetricsCacheType.METRICS_V2_API):
    super(MetricsRegionCacheDao, self).__init__(MetricsRegionCache)
    try:
      self.cache_type = MetricsCacheType(str(cache_type))
    except TypeError:
      raise TypeError("Invalid metrics cache type")

  def get_serving_version_with_session(self, session):
    return (session.query(MetricsRegionCache)
            .order_by(MetricsRegionCache.dateInserted.desc())
            .first())

  def get_active_buckets(self, cutoff, stratification, hpo_ids=None, enrollment_statuses=None):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is None:
        return None
      last_inserted_date = last_inserted_record.dateInserted
      if self.cache_type == MetricsCacheType.PUBLIC_METRICS_EXPORT_API \
        and stratification not in [Stratifications.FULL_AWARDEE, Stratifications.GEO_AWARDEE]:
        query = session.query(MetricsRegionCache.date, MetricsRegionCache.stateName,
                              func.sum(MetricsRegionCache.stateCount).label('total'))
        query = query.filter(MetricsRegionCache.dateInserted == last_inserted_date)
        query = query.filter(MetricsRegionCache.date == cutoff)
        if stratification in [Stratifications.FULL_STATE, Stratifications.FULL_CENSUS,
                              Stratifications.FULL_AWARDEE]:
          query = query.filter(MetricsRegionCache.enrollmentStatus == 'core')
        if hpo_ids:
          query = query.filter(MetricsRegionCache.hpoId.in_(hpo_ids))
        if enrollment_statuses:
          status_filter_list = []
          for status in enrollment_statuses:
            if status == 'INTERESTED':
              status_filter_list.append('registered')
            if status == 'MEMBER':
              status_filter_list.append('consented')
            if status == 'FULL_PARTICIPANT':
              status_filter_list.append('core')
          query = query.filter(MetricsRegionCache.enrollmentStatus.in_(status_filter_list))

        return query.group_by(MetricsRegionCache.date, MetricsRegionCache.stateName).all()
      else:
        query = session.query(MetricsRegionCache.date, MetricsRegionCache.hpoName,
                              MetricsRegionCache.stateName,
                              func.sum(MetricsRegionCache.stateCount).label('total'))
        query = query.filter(MetricsRegionCache.dateInserted == last_inserted_date)
        query = query.filter(MetricsRegionCache.date == cutoff)
        if stratification in [Stratifications.FULL_STATE, Stratifications.FULL_CENSUS,
                              Stratifications.FULL_AWARDEE]:
          query = query.filter(MetricsRegionCache.enrollmentStatus == 'core')
        if hpo_ids:
          query = query.filter(MetricsRegionCache.hpoId.in_(hpo_ids))
        if enrollment_statuses:
          status_filter_list = []
          for status in enrollment_statuses:
            if status == 'INTERESTED':
              status_filter_list.append('registered')
            if status == 'MEMBER':
              status_filter_list.append('consented')
            if status == 'FULL_PARTICIPANT':
              status_filter_list.append('core')
          query = query.filter(MetricsRegionCache.enrollmentStatus.in_(status_filter_list))

        return query.group_by(MetricsRegionCache.date, MetricsRegionCache.hpoName,
                              MetricsRegionCache.stateName).all()

  def get_latest_version_from_cache(self, cutoff, stratification, hpo_ids=None,
                                    enrollment_statuses=None):
    stratification = Stratifications(str(stratification))
    operation_funcs = {
      Stratifications.FULL_STATE: self.to_state_client_json,
      Stratifications.FULL_CENSUS: self.to_census_client_json,
      Stratifications.FULL_AWARDEE: self.to_awardee_client_json,
      Stratifications.GEO_STATE: self.to_state_client_json,
      Stratifications.GEO_CENSUS: self.to_census_client_json,
      Stratifications.GEO_AWARDEE: self.to_awardee_client_json
    }

    buckets = self.get_active_buckets(cutoff, stratification, hpo_ids, enrollment_statuses)
    if buckets is None:
      return []
    return operation_funcs[stratification](buckets)

  def delete_old_records(self, n_days_ago=7):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is not None:
        last_date_inserted = last_inserted_record.dateInserted
        seven_days_ago = last_date_inserted - datetime.timedelta(days=n_days_ago)
        delete_sql = """
          delete from metrics_region_cache where date_inserted < :seven_days_ago
        """
        params = {'seven_days_ago': seven_days_ago}
        session.execute(delete_sql, params)

  def remove_prefix(self, text, prefix):
    if text.startswith(prefix):
      return text[len(prefix):]
    return text

  def to_state_client_json(self, result_set):
    client_json = []
    if self.cache_type == MetricsCacheType.PUBLIC_METRICS_EXPORT_API:
      for record in result_set:
        state_name = self.remove_prefix(record.stateName, 'PIIState_')
        if state_name not in census_regions:
          continue
        is_exist = False
        for item in client_json:
          if item['date'] == record.date.isoformat():
            item['metrics'][state_name] = int(record.total)
            is_exist = True
            break

        if not is_exist:
          metrics = {stateName: 0 for stateName in census_regions.keys()}
          new_item = {
            'date': record.date.isoformat(),
            'metrics': metrics
          }
          new_item['metrics'][state_name] = int(record.total)
          client_json.append(new_item)
    else:
      for record in result_set:
        state_name = self.remove_prefix(record.stateName, 'PIIState_')
        if state_name not in census_regions:
          continue
        is_exist = False
        for item in client_json:
          if item['date'] == record.date.isoformat() and item['hpo'] == record.hpoName:
            item['metrics'][state_name] = int(record.total)
            is_exist = True
            break

        if not is_exist:
          metrics = {stateName: 0 for stateName in census_regions.keys()}
          new_item = {
            'date': record.date.isoformat(),
            'hpo': record.hpoName,
            'metrics': metrics
          }
          new_item['metrics'][state_name] = int(record.total)
          client_json.append(new_item)

    return client_json

  def to_census_client_json(self, result_set):
    client_json = []
    if self.cache_type == MetricsCacheType.PUBLIC_METRICS_EXPORT_API:
      for record in result_set:
        state_name = self.remove_prefix(record.stateName, 'PIIState_')
        if state_name in census_regions:
          census_name = census_regions[state_name]
        else:
          continue
        is_exist = False
        for item in client_json:
          if item['date'] == record.date.isoformat():
            item['metrics'][census_name] += int(record.total)
            is_exist = True
            break

        if not is_exist:
          new_item = {
            'date': record.date.isoformat(),
            'metrics': {
              'NORTHEAST': 0,
              'MIDWEST': 0,
              'SOUTH': 0,
              'WEST': 0
            }
          }
          new_item['metrics'][census_name] = int(record.total)
          client_json.append(new_item)
    else:
      for record in result_set:
        state_name = self.remove_prefix(record.stateName, 'PIIState_')
        if state_name in census_regions:
          census_name = census_regions[state_name]
        else:
          continue
        is_exist = False
        for item in client_json:
          if item['date'] == record.date.isoformat() and item['hpo'] == record.hpoName:
            item['metrics'][census_name] += int(record.total)
            is_exist = True
            break

        if not is_exist:
          new_item = {
            'date': record.date.isoformat(),
            'hpo': record.hpoName,
            'metrics': {
              'NORTHEAST': 0,
              'MIDWEST': 0,
              'SOUTH': 0,
              'WEST': 0
            }
          }
          new_item['metrics'][census_name] = int(record.total)
          client_json.append(new_item)

    return client_json

  def to_awardee_client_json(self, result_set):
    client_json = []
    for record in result_set:
      is_exist = False
      for item in client_json:
        if item['date'] == record.date.isoformat() and item['hpo'] == record.hpoName:
          item['count'] += int(record.total)
          is_exist = True
          break

      if not is_exist:
        new_item = {
          'date': record.date.isoformat(),
          'hpo': record.hpoName,
          'count': int(record.total)
        }
        client_json.append(new_item)
    return client_json

  def get_metrics_cache_sql(self):
    sql = """
      INSERT INTO metrics_region_cache
        SELECT
          :date_inserted AS date_inserted,
          'core' as enrollment_status,
          :hpo_id AS hpo_id,
          (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
          c.day,
          IFNULL(ps.value,'UNSET') AS state_name,
          count(p.participant_id) AS state_count
        FROM participant p INNER JOIN
          (SELECT participant_id, email, value, enrollment_status_core_stored_sample_time FROM participant_summary, code WHERE state_id=code_id) ps ON p.participant_id=ps.participant_id,
          calendar c
        WHERE p.hpo_id=:hpo_id AND p.hpo_id <> :test_hpo_id
        AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
        AND p.withdrawal_status = :not_withdraw
        AND p.is_ghost_id IS NOT TRUE
        AND ps.enrollment_status_core_stored_sample_time IS NOT NULL
        AND DATE(ps.enrollment_status_core_stored_sample_time) <= c.day
        AND c.day BETWEEN :start_date AND :end_date
        GROUP BY c.day, p.hpo_id ,ps.value
        union 
        SELECT
          :date_inserted AS date_inserted,
          'registered' as enrollment_status,
          :hpo_id AS hpo_id,
          (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
          c.day,
          IFNULL(ps.value,'UNSET') AS state_name,
          count(p.participant_id) AS state_count
        FROM participant p INNER JOIN
          (SELECT participant_id, email, value, sign_up_time, enrollment_status_member_time FROM participant_summary, code WHERE state_id=code_id) ps ON p.participant_id=ps.participant_id,
          calendar c
        WHERE p.hpo_id=:hpo_id AND p.hpo_id <> :test_hpo_id
        AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
        AND p.withdrawal_status = :not_withdraw
        AND p.is_ghost_id IS NOT TRUE
        AND ps.sign_up_time IS NOT NULL
        AND DATE(ps.sign_up_time) <= c.day
        AND (ps.enrollment_status_member_time is null or DATE(ps.enrollment_status_member_time)>c.day)
        AND c.day BETWEEN :start_date AND :end_date
        GROUP BY c.day, p.hpo_id ,ps.value
        union 
        SELECT
          :date_inserted AS date_inserted,
          'consented' as enrollment_status,
          :hpo_id AS hpo_id,
          (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
          c.day,
          IFNULL(ps.value,'UNSET') AS state_name,
          count(p.participant_id) AS state_count
        FROM participant p INNER JOIN
          (SELECT participant_id, email, value, enrollment_status_member_time, enrollment_status_core_stored_sample_time FROM participant_summary, code WHERE state_id=code_id) ps ON p.participant_id=ps.participant_id,
          calendar c
        WHERE p.hpo_id=:hpo_id AND p.hpo_id <> :test_hpo_id
        AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
        AND p.withdrawal_status = :not_withdraw
        AND p.is_ghost_id IS NOT TRUE
        AND ps.enrollment_status_member_time IS NOT NULL
        AND DATE(ps.enrollment_status_member_time) <= c.day
        AND (ps.enrollment_status_core_stored_sample_time is null or DATE(ps.enrollment_status_core_stored_sample_time)>c.day)
        AND c.day BETWEEN :start_date AND :end_date
        GROUP BY c.day, p.hpo_id ,ps.value
        ;
    """

    return sql

class MetricsLifecycleCacheDao(BaseDao):

  def __init__(self, cache_type=MetricsCacheType.METRICS_V2_API):
    super(MetricsLifecycleCacheDao, self).__init__(MetricsLifecycleCache)
    try:
      self.cache_type = MetricsCacheType(str(cache_type))
    except TypeError:
      raise TypeError("Invalid metrics cache type")

  def get_serving_version_with_session(self, session):
    return (session.query(MetricsLifecycleCache)
            .order_by(MetricsLifecycleCache.dateInserted.desc())
            .first())

  def get_active_buckets(self, cutoff, hpo_ids=None):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is None:
        return None
      last_inserted_date = last_inserted_record.dateInserted
      if self.cache_type == MetricsCacheType.PUBLIC_METRICS_EXPORT_API:
        query = session.query(MetricsLifecycleCache.date,
                              func.sum(MetricsLifecycleCache.registered)
                              .label('registered'),
                              func.sum(MetricsLifecycleCache.consentEnrollment)
                              .label('consentEnrollment'),
                              func.sum(MetricsLifecycleCache.consentComplete)
                              .label('consentComplete'),
                              func.sum(MetricsLifecycleCache.ppiBasics)
                              .label('ppiBasics'),
                              func.sum(MetricsLifecycleCache.ppiOverallHealth)
                              .label('ppiOverallHealth'),
                              func.sum(MetricsLifecycleCache.ppiLifestyle)
                              .label('ppiLifestyle'),
                              func.sum(MetricsLifecycleCache.ppiHealthcareAccess)
                              .label('ppiHealthcareAccess'),
                              func.sum(MetricsLifecycleCache.ppiMedicalHistory)
                              .label('ppiMedicalHistory'),
                              func.sum(MetricsLifecycleCache.ppiMedications)
                              .label('ppiMedications'),
                              func.sum(MetricsLifecycleCache.ppiFamilyHealth)
                              .label('ppiFamilyHealth'),
                              func.sum(MetricsLifecycleCache.ppiBaselineComplete)
                              .label('ppiBaselineComplete'),
                              func.sum(MetricsLifecycleCache.physicalMeasurement)
                              .label('physicalMeasurement'),
                              func.sum(MetricsLifecycleCache.sampleReceived)
                              .label('sampleReceived'),
                              func.sum(MetricsLifecycleCache.fullParticipant)
                              .label('fullParticipant')
                              )
        query = query.filter(MetricsLifecycleCache.dateInserted == last_inserted_date)
        query = query.filter(MetricsLifecycleCache.date == cutoff)

        if hpo_ids:
          query = query.filter(MetricsLifecycleCache.hpoId.in_(hpo_ids))

        return query.group_by(MetricsLifecycleCache.date).all()
      else:
        query = session.query(MetricsLifecycleCache) \
          .filter(MetricsLifecycleCache.dateInserted == last_inserted_date)
        query = query.filter(MetricsLifecycleCache.date == cutoff)

        if hpo_ids:
          query = query.filter(MetricsLifecycleCache.hpoId.in_(hpo_ids))

        return query.all()

  def get_primary_consent_count_over_time(self, start_date, end_date, hpo_ids=None):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is None:
        return None
      last_inserted_date = last_inserted_record.dateInserted
      query = session.query(MetricsLifecycleCache.date,
                            func.sum(MetricsLifecycleCache.consentEnrollment)
                            .label('primaryConsent'))
      query = query.filter(MetricsLifecycleCache.dateInserted == last_inserted_date)
      query = query.filter(MetricsLifecycleCache.date >= start_date)
      query = query.filter(MetricsLifecycleCache.date <= end_date)

      if hpo_ids:
        query = query.filter(MetricsLifecycleCache.hpoId.in_(hpo_ids))

      result_set = query.group_by(MetricsLifecycleCache.date).all()
      client_json = []
      for record in result_set:
        new_item = {
          'date': record.date.isoformat(),
          'metrics': {
            'Primary_Consent': int(record.primaryConsent)
          }
        }
        client_json.append(new_item)
      return client_json

  def get_latest_version_from_cache(self, cutoff, hpo_ids=None):
    buckets = self.get_active_buckets(cutoff, hpo_ids)
    if buckets is None:
      return []
    operation_funcs = {
      MetricsCacheType.PUBLIC_METRICS_EXPORT_API: self.to_public_metrics_client_json,
      MetricsCacheType.METRICS_V2_API: self.to_metrics_client_json
    }
    return operation_funcs[self.cache_type](buckets)

  def delete_old_records(self, n_days_ago=7):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is not None:
        last_date_inserted = last_inserted_record.dateInserted
        seven_days_ago = last_date_inserted - datetime.timedelta(days=n_days_ago)
        delete_sql = """
          delete from metrics_lifecycle_cache where date_inserted < :seven_days_ago
        """
        params = {'seven_days_ago': seven_days_ago}
        session.execute(delete_sql, params)

  def to_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      new_item = {
        'date': record.date.isoformat(),
        'hpo': record.hpoName,
        'metrics': {
          'completed': {
            'Registered': record.registered,
            'Consent_Enrollment': record.consentEnrollment,
            'Consent_Complete': record.consentComplete,
            'PPI_Module_The_Basics': record.ppiBasics,
            'PPI_Module_Overall_Health': record.ppiOverallHealth,
            'PPI_Module_Lifestyle': record.ppiLifestyle,
            'Baseline_PPI_Modules_Complete': record.ppiBaselineComplete,
            'Physical_Measurements': record.physicalMeasurement,
            'Samples_Received': record.sampleReceived,
            'Full_Participant': record.fullParticipant
          },
          'not_completed': {
            'Registered': 0,
            'Consent_Enrollment': record.registered - record.consentEnrollment,
            'Consent_Complete': record.consentEnrollment - record.consentComplete,
            'PPI_Module_The_Basics': record.consentEnrollment - record.ppiBasics,
            'PPI_Module_Overall_Health': record.consentEnrollment - record.ppiOverallHealth,
            'PPI_Module_Lifestyle': record.consentEnrollment - record.ppiLifestyle,
            'Baseline_PPI_Modules_Complete': record.consentEnrollment - record.ppiBaselineComplete,
            'Physical_Measurements': record.consentEnrollment - record.physicalMeasurement,
            'Samples_Received': record.consentEnrollment - record.sampleReceived,
            'Full_Participant': record.consentEnrollment - record.fullParticipant
          }
        }
      }
      client_json.append(new_item)
    return client_json

  def to_public_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      new_item = {
        'date': record.date.isoformat(),
        'metrics': {
          'completed': {
            'Registered': int(record.registered),
            'Consent_Enrollment': int(record.consentEnrollment),
            'Consent_Complete': int(record.consentComplete),
            'PPI_Module_The_Basics': int(record.ppiBasics),
            'PPI_Module_Overall_Health': int(record.ppiOverallHealth),
            'PPI_Module_Lifestyle': int(record.ppiLifestyle),
            'PPI_Module_Healthcare_Access': int(record.ppiHealthcareAccess),
            'PPI_Module_Medical_History': int(record.ppiMedicalHistory),
            'PPI_Module_Medications': int(record.ppiMedications),
            'PPI_Module_Family_Health': int(record.ppiFamilyHealth),
            'Baseline_PPI_Modules_Complete': int(record.ppiBaselineComplete),
            'Physical_Measurements': int(record.physicalMeasurement),
            'Samples_Received': int(record.sampleReceived),
            'Full_Participant': int(record.fullParticipant)
          },
          'not_completed': {
            'Registered': 0,
            'Consent_Enrollment': int(record.registered - record.consentEnrollment),
            'Consent_Complete': int(record.consentEnrollment - record.consentComplete),
            'PPI_Module_The_Basics': int(record.consentEnrollment - record.ppiBasics),
            'PPI_Module_Overall_Health': int(record.consentEnrollment - record.ppiOverallHealth),
            'PPI_Module_Lifestyle': int(record.consentEnrollment - record.ppiLifestyle),
            'PPI_Module_Healthcare_Access': int(record.consentEnrollment -
                                                record.ppiHealthcareAccess),
            'PPI_Module_Medical_History': int(record.consentEnrollment - record.ppiMedicalHistory),
            'PPI_Module_Medications': int(record.consentEnrollment - record.ppiMedications),
            'PPI_Module_Family_Health': int(record.consentEnrollment - record.ppiFamilyHealth),
            'Baseline_PPI_Modules_Complete': int(record.consentEnrollment -
                                                 record.ppiBaselineComplete),
            'Physical_Measurements': int(record.consentEnrollment - record.physicalMeasurement),
            'Samples_Received': int(record.consentEnrollment - record.sampleReceived),
            'Full_Participant': int(record.consentEnrollment - record.fullParticipant)
          }
        }
      }
      client_json.append(new_item)
    return client_json

  def get_metrics_cache_sql(self):
    sql = """
      insert into metrics_lifecycle_cache
        select
          :date_inserted AS date_inserted,
          p.hpo_id,
          (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
          day,
          SUM(CASE WHEN DATE(p.sign_up_time) <= calendar.day THEN 1 ELSE 0 END) AS registered,
          SUM(CASE WHEN DATE(ps.consent_for_study_enrollment_time) <= calendar.day THEN 1 ELSE 0 END) AS consent_enrollment,
          SUM(CASE WHEN DATE(ps.enrollment_status_member_time) <= calendar.day THEN 1 ELSE 0 END) AS consent_complete,
          SUM(CASE
            WHEN
              DATE(ps.questionnaire_on_the_basics_time) <= calendar.day AND
              DATE(ps.consent_for_study_enrollment_time) <= calendar.day
            THEN 1 ELSE 0
          END) AS ppi_basics,
          SUM(CASE
            WHEN
              DATE(ps.questionnaire_on_overall_health_time) <= calendar.day AND
              DATE(ps.consent_for_study_enrollment_time) <= calendar.day
            THEN 1 ELSE 0
          END) AS ppi_overall_health,
          SUM(CASE
            WHEN
              DATE(ps.questionnaire_on_lifestyle_time) <= calendar.day AND
              DATE(ps.consent_for_study_enrollment_time) <= calendar.day
            THEN 1 ELSE 0
          END) AS ppi_lifestyle,
          SUM(CASE
            WHEN
              DATE(ps.questionnaire_on_healthcare_access_time) <= calendar.day AND
              DATE(ps.consent_for_study_enrollment_time) <= calendar.day
            THEN 1 ELSE 0
          END) AS ppi_healthcare_access,
          SUM(CASE
            WHEN
              DATE(ps.questionnaire_on_medical_history_time) <= calendar.day AND
              DATE(ps.consent_for_study_enrollment_time) <= calendar.day
            THEN 1 ELSE 0
          END) AS ppi_medical_history,
          SUM(CASE
            WHEN
              DATE(ps.questionnaire_on_medications_time) <= calendar.day AND
              DATE(ps.consent_for_study_enrollment_time) <= calendar.day
            THEN 1 ELSE 0
          END) AS ppi_medications,
          SUM(CASE
            WHEN
              DATE(ps.questionnaire_on_family_health_time) <= calendar.day AND
              DATE(ps.consent_for_study_enrollment_time) <= calendar.day
            THEN 1 ELSE 0
          END) AS ppi_family_health,
          SUM(CASE
            WHEN
              DATE(ps.questionnaire_on_lifestyle_time) <= calendar.day AND
              DATE(ps.questionnaire_on_overall_health_time) <= calendar.day AND
              DATE(ps.questionnaire_on_the_basics_time) <= calendar.day AND
              DATE(ps.consent_for_study_enrollment_time) <= calendar.day
            THEN 1 ELSE 0
          END) AS ppi_complete,
          SUM(CASE
            WHEN
              DATE(ps.physical_measurements_time) <= calendar.day AND
              DATE(ps.consent_for_study_enrollment_time) <= calendar.day
            THEN 1 ELSE 0
          END) AS physical_measurement,
          SUM(CASE
            WHEN
              DATE(ps.sample_status_1ed10_time) <= calendar.day OR
              DATE(ps.sample_status_2ed10_time) <= calendar.day OR
              DATE(ps.sample_status_1ed04_time) <= calendar.day OR
              DATE(ps.sample_status_1sal_time) <= calendar.day OR
              DATE(ps.sample_status_1sal2_time) <= calendar.day
            THEN 1 ELSE 0
          END) AS sample_received,
          SUM(CASE WHEN DATE(ps.enrollment_status_core_stored_sample_time) <= calendar.day THEN 1 ELSE 0 END) AS core_participant
        from participant p LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id,
             calendar
        WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
          AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
          AND p.withdrawal_status = :not_withdraw
          AND p.is_ghost_id IS NOT TRUE
          AND calendar.day BETWEEN :start_date AND :end_date
        GROUP BY day, p.hpo_id;
    """
    return sql

class MetricsLanguageCacheDao(BaseDao):

  def __init__(self, cache_type=MetricsCacheType.METRICS_V2_API):
    super(MetricsLanguageCacheDao, self).__init__(MetricsLanguageCache)
    try:
      self.cache_type = MetricsCacheType(str(cache_type))
    except TypeError:
      raise TypeError("Invalid metrics cache type")

  def get_serving_version_with_session(self, session):
    return (session.query(MetricsLanguageCache)
            .order_by(MetricsLanguageCache.dateInserted.desc())
            .first())

  def get_active_buckets(self, start_date=None, end_date=None, hpo_ids=None,
                         enrollment_statuses=None):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is None:
        return None
      last_inserted_date = last_inserted_record.dateInserted
      if self.cache_type == MetricsCacheType.PUBLIC_METRICS_EXPORT_API:
        query = session.query(MetricsLanguageCache.date, MetricsLanguageCache.languageName,
                              func.sum(MetricsLanguageCache.languageCount).label('total'))
      else:
        query = session.query(MetricsLanguageCache.date, MetricsLanguageCache.hpoName,
                              MetricsLanguageCache.languageName,
                              func.sum(MetricsLanguageCache.languageCount).label('total'))
      query = query.filter(MetricsLanguageCache.dateInserted == last_inserted_date)
      if start_date:
        query = query.filter(MetricsLanguageCache.date >= start_date)
      if end_date:
        query = query.filter(MetricsLanguageCache.date <= end_date)

      if hpo_ids:
        query = query.filter(MetricsLanguageCache.hpoId.in_(hpo_ids))
      if enrollment_statuses:
        status_filter_list = []
        for status in enrollment_statuses:
          if status == 'INTERESTED':
            status_filter_list.append('registered')
          if status == 'MEMBER':
            status_filter_list.append('consented')
          if status == 'FULL_PARTICIPANT':
            status_filter_list.append('core')
        query = query.filter(MetricsLanguageCache.enrollmentStatus.in_(status_filter_list))

      if self.cache_type == MetricsCacheType.PUBLIC_METRICS_EXPORT_API:
        return query.group_by(MetricsLanguageCache.date, MetricsLanguageCache.languageName).all()
      else:
        return query.group_by(MetricsLanguageCache.date, MetricsLanguageCache.hpoName,
                              MetricsLanguageCache.languageName).all()

  def get_latest_version_from_cache(self, start_date, end_date, hpo_ids=None,
                                    enrollment_statuses=None):

    buckets = self.get_active_buckets(start_date, end_date, hpo_ids, enrollment_statuses)
    if buckets is None:
      return []

    operation_funcs = {
      MetricsCacheType.PUBLIC_METRICS_EXPORT_API: self.to_public_metrics_client_json,
      MetricsCacheType.METRICS_V2_API: self.to_metrics_client_json
    }
    return operation_funcs[self.cache_type](buckets)

  def delete_old_records(self, n_days_ago=7):
    with self.session() as session:
      last_inserted_record = self.get_serving_version_with_session(session)
      if last_inserted_record is not None:
        last_date_inserted = last_inserted_record.dateInserted
        seven_days_ago = last_date_inserted - datetime.timedelta(days=n_days_ago)
        delete_sql = """
          delete from metrics_language_cache where date_inserted < :seven_days_ago
        """
        params = {'seven_days_ago': seven_days_ago}
        session.execute(delete_sql, params)

  def to_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      language_name = record.languageName
      is_exist = False
      for item in client_json:
        if item['date'] == record.date.isoformat() and item['hpo'] == record.hpoName:
          item['metrics'][language_name] = int(record.total)
          is_exist = True
          break

      if not is_exist:
        new_item = {
          'date': record.date.isoformat(),
          'hpo': record.hpoName,
          'metrics': {
            'EN': 0,
            'ES': 0,
            'UNSET': 0
          }
        }
        new_item['metrics'][language_name] = int(record.total)
        client_json.append(new_item)
    return client_json

  def to_public_metrics_client_json(self, result_set):
    client_json = []
    for record in result_set:
      language_name = record.languageName
      is_exist = False
      for item in client_json:
        if item['date'] == record.date.isoformat():
          item['metrics'][language_name] = int(record.total)
          is_exist = True
          break

      if not is_exist:
        new_item = {
          'date': record.date.isoformat(),
          'metrics': {
            'EN': 0,
            'ES': 0,
            'UNSET': 0
          }
        }
        new_item['metrics'][language_name] = int(record.total)
        client_json.append(new_item)
    return client_json

  def get_metrics_cache_sql(self):
    sql = """
      insert into metrics_language_cache 
    """

    enrollment_status_and_criteria_list = [
      ['registered', ' c.day>=DATE(sign_up_time) AND (enrollment_status_member_time IS NULL '
                     'OR c.day < DATE(enrollment_status_member_time)) '],
      ['consented', ' enrollment_status_member_time IS NOT NULL '
                    'AND day>=DATE(enrollment_status_member_time) '
                    'AND (enrollment_status_core_stored_sample_time IS NULL '
                    'OR day < DATE(enrollment_status_core_stored_sample_time)) '],
      ['core', ' enrollment_status_core_stored_sample_time IS NOT NULL '
               'AND day>=DATE(enrollment_status_core_stored_sample_time) ']
    ]
    language_and_criteria_list = [
      ['EN', ' AND ps.primary_language like \'%en%\' '],
      ['ES', ' AND ps.primary_language like \'%es%\' '],
      ['UNSET', ' AND ps.primary_language is NULL ']
    ]

    sql_template = """
      select
      :date_inserted AS date_inserted,
      '{0}' as enrollment_status,
      :hpo_id AS hpo_id,
      (SELECT name FROM hpo WHERE hpo_id=:hpo_id) AS hpo_name,
      c.day,
      '{1}' AS language_name,
      IFNULL((
          SELECT SUM(results.count)
          FROM
          (
            SELECT DATE(p.sign_up_time) AS sign_up_time,
                   DATE(ps.enrollment_status_member_time) AS enrollment_status_member_time,
                   DATE(ps.enrollment_status_core_stored_sample_time) AS enrollment_status_core_stored_sample_time,
                   count(*) count
            FROM participant p
                   LEFT JOIN participant_summary ps ON p.participant_id = ps.participant_id
            WHERE p.hpo_id = :hpo_id AND p.hpo_id <> :test_hpo_id
              AND p.is_ghost_id IS NOT TRUE
              AND (ps.email IS NULL OR NOT ps.email LIKE :test_email_pattern)
              AND p.withdrawal_status = :not_withdraw
              {2}
            GROUP BY DATE(p.sign_up_time), DATE(ps.enrollment_status_member_time), DATE(ps.enrollment_status_core_stored_sample_time)
          ) AS results
          WHERE {3}
        ),0) AS language_count
      FROM calendar c
      WHERE c.day BETWEEN :start_date AND :end_date
    """

    sub_queries = []

    for status_pairs in enrollment_status_and_criteria_list:
      for language_pairs in language_and_criteria_list:
        sub_query = sql_template.format(status_pairs[0], language_pairs[0], language_pairs[1],
                                        status_pairs[1])
        sub_queries.append(sub_query)

    sql = sql + ' UNION '.join(sub_queries)

    return sql
