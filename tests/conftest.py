"""Shared fixtures: synthetic Indeed search pages (no network, no API credit)."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

# 2026-09-24 00:00 US Central, the way Indeed stamps `pubDate`.
PUB_DATE_MS = 1790226000000


def make_card(**overrides: Any) -> dict[str, Any]:
    """An Indeed embedded job card, shaped like the real thing."""
    card: dict[str, Any] = {
        "jobkey": "a601cb49ef4ef3e1",
        "displayTitle": "Python Developer",
        "title": "Python Developer",
        "company": "Example Labs",
        "truncatedCompany": "Example Labs",
        "companyOverviewLink": "/cmp/Example-Labs?campaignid=serp&from=serp",
        "companyRating": 4.6,
        "companyReviewCount": 91,
        "formattedLocation": "Austin, TX 78701",
        "jobLocationCity": "Austin",
        "jobLocationState": "TX",
        "jobLocationPostal": "78701",
        "country": "US",
        "remoteLocation": False,
        "remoteWorkModel": {"inlineText": True, "text": "Hybrid work", "type": "REMOTE_HYBRID"},
        "salarySnippet": {
            "currency": "USD",
            "salaryTextFormatted": False,
            "source": "EXTRACTION",
            "text": "$120,000 - $150,000 a year",
        },
        "extractedSalary": {"max": 150000, "min": 120000, "type": "YEARLY"},
        "jobTypes": ["Full-time"],
        "pubDate": PUB_DATE_MS,
        "createDate": PUB_DATE_MS + 12345678,
        "formattedRelativeTime": "3 days ago",
        "sponsored": False,
        "urgentlyHiring": False,
        "indeedApplyable": True,
        "snippet": '<ul style="list-style-type:circle;">\n <li>Build <b>Python</b> APIs &amp; '
        "services.</li>\n <li>Own the data pipeline.</li>\n</ul>",
        "tier": {
            "matchedPreferences": {"longMatchedPreferences": [], "stringMatchedPreferences": []},
            "type": "DEFAULT",
        },
        "link": "/rc/clk?jk=a601cb49ef4ef3e1&bb=tracking",
    }
    for key, value in overrides.items():
        card[key] = value
    return copy.deepcopy(card)


def related_tier(label: str = "Jobs in mobile app development") -> dict[str, Any]:
    return {"jobGroupId": "ab103147", "rawType": f"grouping_{label}", "type": "DEFAULT"}


NEARBY_TIER = {"rawType": "LocationExpansionSponsoredGrouping", "type": "LE_SPONSORED_GROUPING"}
RECOMMENDED_TIER = {"rawType": "rjponserp", "type": "RJP_ON_SERP"}


def make_details_body(job_key: str = "a601cb49ef4ef3e1", **overrides: Any) -> dict[str, Any]:
    """The side-panel posting Indeed embeds as ``autoOpenTwoPaneViewjobResponse.body``."""
    body: dict[str, Any] = {
        "jobKey": job_key,
        "jobTitle": "Python Developer",
        "jobLocation": "Austin, TX",
        "jobInfoWrapperModel": {
            "jobInfoModel": {
                "jobInfoHeaderModel": {
                    "jobTitle": "Python Developer",
                    "companyName": "Example Labs",
                    "formattedLocation": "Austin, TX",
                    "companyOverviewLink": "https://www.indeed.com/cmp/Example-Labs?campaignid=vj",
                    "companyImagesModel": {"logoUrl": "https://images.example.com/logo.png"},
                    "companyReviewModel": {"ratingsModel": {"rating": 4.6, "count": 91}},
                    "remoteWorkModel": {"text": "Hybrid work", "type": "REMOTE_HYBRID"},
                },
                "sanitizedJobDescription": "<div><p><b>About the role</b></p><p>Build APIs.</p>"
                "<ul><li>Python 3</li><li>PostgreSQL &amp; Redis</li></ul></div>",
                "showExpiredHeader": False,
                "jobDescriptionSectionModel": {
                    "jobDetailsSection": {
                        "isJobExpired": False,
                        "jobTypes": [{"label": "Full-time", "suid": "CF3CP"}],
                        "salaryInfoModel": None,
                    }
                },
            }
        },
        "salaryInfoModel": {
            "salaryCurrency": "USD",
            "salaryMax": 150000,
            "salaryMin": 120000,
            "salaryText": "$120,000 - $150,000 a year",
            "salaryType": "YEARLY",
        },
        "benefitsModel": {
            "benefits": [
                {"key": "FVKX2", "label": "401(k)"},
                {"key": "EY33Q", "label": "Health insurance"},
            ]
        },
        "hiringInsightsModel": {"age": "3 days ago"},
    }
    for key, value in overrides.items():
        body[key] = value
    return copy.deepcopy(body)


def make_page_html(
    cards: list[dict[str, Any]],
    *,
    what: str = "python developer",
    where: str = "Austin, TX",
    total: int | None = 2431,
    details: dict[str, Any] | None = None,
) -> str:
    """Wrap ``cards`` in an Indeed-style results page with its embedded data blocks."""
    jobcards = {
        "metaData": {
            "mosaicProviderJobCardsModel": {
                "results": cards,
                "what": what,
                "where": where,
                "pageNumber": 1,
                "ipCountry": "US",
            }
        }
    }
    initial: dict[str, Any] = {"country": "US"}
    if total is not None:
        initial["totalJobCount"] = total
        initial["searchTitleBarModel"] = {"totalNumResults": total}
    if details is not None:
        initial["autoOpenTwoPaneViewjobResponse"] = {"body": details}
    return (
        "<html><head><title>Python Developer Jobs | Indeed</title></head><body>"
        f"<script>window._initialData={json.dumps(initial)};\nwindow.other = {{}};</script>"
        '<script>window.mosaic.providerData["mosaic-provider-jobcards"]='
        f"{json.dumps(jobcards)};\nwindow.mosaic.x = 1;</script>"
        "</body></html>"
    )


SIGN_IN_HTML = (
    "<html><head><title>\n    Sign In | Indeed Accounts\n  </title></head><body>"
    '<script>window.model = {"pageCode":"auth","countryCode":"US"};</script></body></html>'
)

CHALLENGE_HTML = (
    "<html><head><title>Just a moment...</title></head><body>"
    "<script>window._cf_chl_opt={cvId: '3'};</script></body></html>"
)


@pytest.fixture
def card() -> dict[str, Any]:
    return make_card()
