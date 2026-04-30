from __future__ import annotations

from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.tools.identity_domain_tools import IdentityDomainTools


class FakeIdentityClient:
    def __init__(self):
        self.last_payload = None

    def create_user(self, payload):
        self.last_payload = payload
        return {"id": "u-created", "userName": payload["userName"]}


class FakeHrTools:
    def __init__(self, candidates):
        self.candidates = candidates

    def query_hr_database(self, payload):
        return NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"candidates": self.candidates, "candidate_count": len(self.candidates)},
            audit=AuditPayload(result="success"),
        )


class CapturingHrTools(FakeHrTools):
    def __init__(self, candidates):
        super().__init__(candidates)
        self.last_payload = None

    def query_hr_database(self, payload):
        self.last_payload = payload
        return super().query_hr_database(payload)


class FakeHrToolsError:
    def query_hr_database(self, payload):
        return NormalizedResponse.error(
            message="HR DB照会に失敗しました。",
            code="temporary_upstream_failure",
            retryable=True,
            proposal=["DB接続情報を確認してください。"],
            audit=AuditPayload(result="error"),
        )


class FakeHrToolsFallback:
    def __init__(self):
        self.calls: list[dict[str, str]] = []

    def query_hr_database(self, payload):
        self.calls.append(payload)
        if len(self.calls) == 1:
            return NormalizedResponse.success(
                facts=["ok"],
                interpretation=["ok"],
                proposal=["ok"],
                data={"candidates": [], "candidate_count": 0},
                audit=AuditPayload(result="success"),
            )
        return NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={
                "candidates": [
                    {
                        "first_name": "Hanako",
                        "last_name": "Kato",
                        "email": "hanako.kato@example.com",
                    }
                ],
                "candidate_count": 1,
            },
            audit=AuditPayload(result="success"),
        )


def test_us3_missing_input_is_supplemented_by_hr_single_candidate() -> None:
    candidates = [{"first_name": "Taro", "last_name": "Yamada", "email": "taro@example.com"}]
    tools = IdentityDomainTools(client=FakeIdentityClient(), hr_tools=FakeHrTools(candidates))

    response = tools.create_user({"email": "taro@example.com"})
    assert response.status == "success"
    assert response.data is not None
    assert response.data["supplemented_from_hr"] is True


def test_us3_missing_input_error_when_hr_has_no_candidate() -> None:
    tools = IdentityDomainTools(client=FakeIdentityClient(), hr_tools=FakeHrTools([]))

    response = tools.create_user({"email": "taro@example.com"})
    assert response.status == "error"
    assert response.errors is not None
    assert response.errors[0].code == "missing_input"


def test_us3_hr_query_payload_maps_kanji_family_name() -> None:
    hr_tools = CapturingHrTools([{"first_name": "Taro", "last_name": "Tanaka", "email": "taro.tanaka@example.com"}])
    tools = IdentityDomainTools(client=FakeIdentityClient(), hr_tools=hr_tools)

    response = tools.create_user({"family_name_kanji": "田中"})
    assert response.status == "success"
    assert hr_tools.last_payload == {"last_name_kanji": "田中"}


def test_us3_hr_supplement_overwrites_unresolved_refs() -> None:
    identity_client = FakeIdentityClient()
    hr_tools = FakeHrTools([{"first_name": "Ken", "last_name": "Tanaka", "email": "ken.tanaka@example.com"}])
    tools = IdentityDomainTools(client=identity_client, hr_tools=hr_tools)

    response = tools.create_user(
        {
            "family_name_kanji": "田中",
            "email": "${step1.result.email}",
            "username": "${step1.result.user_name}",
        }
    )

    assert response.status == "success"
    assert identity_client.last_payload is not None
    assert identity_client.last_payload["userName"] == "ken.tanaka@example.com"
    assert identity_client.last_payload["emails"][0]["value"] == "ken.tanaka@example.com"
    assert identity_client.last_payload["name"]["familyName"] == "Tanaka"
    assert identity_client.last_payload["name"]["givenName"] == "Ken"


def test_us3_create_user_returns_hr_error_when_lookup_fails() -> None:
    tools = IdentityDomainTools(client=FakeIdentityClient(), hr_tools=FakeHrToolsError())

    response = tools.create_user({"family_name_kanji": "山田"})
    assert response.status == "error"
    assert response.errors is not None
    assert response.errors[0].code == "temporary_upstream_failure"


def test_us3_create_user_username_is_forced_to_email() -> None:
    identity_client = FakeIdentityClient()
    tools = IdentityDomainTools(client=identity_client, hr_tools=FakeHrTools([]))

    response = tools.create_user(
        {
            "family_name": "Suzuki",
            "given_name": "Hanako",
            "email": "hanako.suzuki@example.com",
            "username": "suzuki",
        }
    )

    assert response.status == "success"
    assert identity_client.last_payload is not None
    assert identity_client.last_payload["userName"] == "hanako.suzuki@example.com"


def test_us3_hr_lookup_retries_without_email_when_name_filter_has_no_match() -> None:
    identity_client = FakeIdentityClient()
    hr_tools = FakeHrToolsFallback()
    tools = IdentityDomainTools(client=identity_client, hr_tools=hr_tools)

    response = tools.create_user(
        {
            "email": "wrong.address@example.com",
            "family_name_kanji": "加藤",
        }
    )

    assert response.status == "success"
    assert hr_tools.calls == [
        {"email": "wrong.address@example.com", "last_name_kanji": "加藤"},
        {"last_name_kanji": "加藤"},
    ]
    assert identity_client.last_payload is not None
    assert identity_client.last_payload["userName"] == "wrong.address@example.com"
    assert identity_client.last_payload["name"]["familyName"] == "Kato"
    assert identity_client.last_payload["name"]["givenName"] == "Hanako"
