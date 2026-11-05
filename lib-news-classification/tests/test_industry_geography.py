import pytest
import news_subject


@pytest.mark.parametrize('region,route', [('ID','id_industry_news'),('US','us_industry_news'),('GLOBAL','global_industry_news'),('UNKNOWN','global_industry_news')])
def test_industry_region_selects_destination_independently_of_company_examples(region, route):
    subject={'kind':'industry','name':'Semiconductors','evidence':'US sector index fell','industry':{'region':region}}
    assert news_subject.validate_subject(subject,'US sector index fell') == subject
    assert news_subject.route_for(subject) == route
    assert news_subject.validate_route(subject,route) == route
    for wrong in news_subject.GEOGRAPHIC_NEWS_ROUTES | {'macro_news'} - {route}:
        if wrong != route:
            with pytest.raises(ValueError,match='route conflicts'):
                news_subject.validate_route(subject,wrong)


def test_legacy_industry_subject_preserves_saved_indonesia_route():
    legacy={'kind':'industry','name':'Old industry','evidence':'Old evidence'}
    assert news_subject.route_for(legacy)=='id_industry_news'


@pytest.mark.parametrize('details',[{'region':'CN'},{'region':'US','exchange':'NYSE'},{}, {'region':None}])
def test_industry_geography_is_closed(details):
    with pytest.raises(ValueError,match='industry'):
        news_subject.validate_subject({'kind':'industry','name':'Industry','evidence':'Source','industry':details})
