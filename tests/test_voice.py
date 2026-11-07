from decimal import Decimal

import pytest

from apps.catalog.models import Service
from apps.voice import llm
from apps.voice.models import VoiceUsage

URL = "/api/v1/voice/draft/"


@pytest.fixture
def model(monkeypatch, settings):
    """Stands in for the provider; records what it was sent."""
    settings.ANTHROPIC_API_KEY = "test-key"
    calls = []

    def respond(answer):
        def extract(system, text, schema):
            calls.append({"system": system, "text": text, "schema": schema})
            return llm.Extraction(answer, 1200, 300)

        monkeypatch.setattr(llm, "extract", extract)
        return calls

    return respond


def test_patient_draft_cleans_values(world, model):
    model(
        {
            "full_name": "Aliyev Vali",
            "phone_number": "90 123 45 67",
            "birth_date": "1990-05-04",
            "gender": "male",
            "address": "Toshkent",
            "notes": "Tish og'rig'i",
        }
    )
    response = world.client(world.doctor_a).post(URL, {"form": "patient", "text": "Aliyev Vali ..."}, format="json")
    assert response.status_code == 200
    body = response.json()
    assert body["patient_fields"] == {
        "full_name": "Aliyev Vali",
        "phone_number": "+998901234567",
        "birth_date": "1990-05-04",
        "gender": "male",
        "address": "Toshkent",
    }
    assert body["notes"] == "Tish og'rig'i"
    usage = VoiceUsage.objects.get()
    assert (usage.clinic, usage.member, usage.input_tokens) == (world.branch_a, world.doctor_a, 1200)


def test_bad_values_are_dropped_not_guessed(world, model):
    model(
        {"full_name": "X", "phone_number": "12", "birth_date": "2999-01-01", "gender": "?", "address": "", "notes": ""}
    )
    body = world.client(world.doctor_a).post(URL, {"form": "patient", "text": "abc"}, format="json").json()
    assert body["patient_fields"]["phone_number"] == ""
    assert body["patient_fields"]["birth_date"] is None
    assert body["patient_fields"]["gender"] == ""


def test_procedure_matches_price_list_and_visible_patient(world, model):
    filling = Service.objects.create(clinic=world.branch_a, name="Plomba", price=Decimal("150000"))
    Service.objects.create(clinic=world.branch_b, name="Plomba B", price=Decimal("1"))
    calls = model(
        {
            "patient_name": "Patient A",
            "items": [
                {"service": "Plomba", "heard": "plomba qo'ydim", "tooth": 36},
                {"service": "", "heard": "nimadir", "tooth": 99},
            ],
            "notes": "",
        }
    )
    body = world.client(world.doctor_a).post(URL, {"form": "procedure", "text": "..."}, format="json").json()
    assert body["patient"]["id"] == str(world.patient_a.pk)
    assert body["procedures"][0] == {
        "service": str(filling.pk),
        "service_name": "Plomba",
        "unit_price": "150000.00",
        "heard": "plomba qo'ydim",
        "tooth": 36,
    }
    assert body["procedures"][1]["service"] is None
    assert body["procedures"][1]["tooth"] is None
    # Only this clinic's price list is shown to the model, and no patient names.
    assert "Plomba B" not in calls[0]["system"]
    assert "Patient A2" not in calls[0]["system"]


def test_doctor_never_gets_a_colleagues_patient(world, model):
    model({"patient_name": "Patient A2", "items": [], "notes": ""})
    body = world.client(world.doctor_a).post(URL, {"form": "prescription", "text": "..."}, format="json").json()
    assert body["patient"] is None
    assert body["patient_candidates"] == [
        {"id": str(world.patient_a.pk), "full_name": "Patient A"}
    ]  # matched on the word "Patient" only, never A2


def test_prescription_items(world, model):
    model(
        {
            "patient_name": "",
            "items": [
                {
                    "medicine": "Amoxicillin",
                    "dose": "500 mg",
                    "form": "tablet",
                    "times_per_day": 3,
                    "duration_days": 7,
                    "meal_relation": "after",
                    "instructions": "",
                },
                {
                    "medicine": "Ibuprofen",
                    "dose": "",
                    "form": "pill",
                    "times_per_day": 0,
                    "duration_days": None,
                    "meal_relation": "never",
                    "instructions": "",
                },
            ],
            "notes": "",
        }
    )
    response = world.client(world.doctor_a).post(
        URL, {"form": "prescription", "text": "...", "patient": str(world.patient_a.pk)}, format="json"
    )
    body = response.json()
    assert body["patient"]["id"] == str(world.patient_a.pk)
    assert body["medicines"][0]["times_per_day"] == 3
    assert body["medicines"][1]["times_per_day"] is None
    assert body["medicines"][1]["meal_relation"] == "any"
    assert body["medicines"][1]["form"] == ""


def test_patient_context_is_tenant_and_doctor_scoped(world, model):
    model({"patient_name": "", "items": [], "notes": ""})
    api = world.client(world.doctor_a)
    other = api.post(URL, {"form": "procedure", "text": "...", "patient": str(world.patient_other.pk)}, format="json")
    assert other.status_code == 400
    colleague = api.post(URL, {"form": "procedure", "text": "...", "patient": str(world.patient_a2.pk)}, format="json")
    assert colleague.status_code == 400


def test_needs_the_forms_own_permission(world, model, monkeypatch):
    model({"patient_name": "", "items": [], "notes": ""})
    from apps.tenancy import permissions

    doctor = permissions.ROLE_PERMISSIONS["doctor"] - {"prescription:manage"}
    monkeypatch.setitem(permissions.ROLE_PERMISSIONS, "doctor", doctor)
    response = world.client(world.doctor_a).post(URL, {"form": "prescription", "text": "..."}, format="json")
    assert response.status_code == 403


def test_off_without_key(world, settings):
    settings.ANTHROPIC_API_KEY = ""
    api = world.client(world.doctor_a)
    assert api.get("/api/v1/voice/status/").json()["enabled"] is False
    assert api.post(URL, {"form": "patient", "text": "abc"}, format="json").status_code == 503
    assert not VoiceUsage.objects.exists()


def test_provider_failure_is_generic(world, monkeypatch, settings):
    settings.ANTHROPIC_API_KEY = "test-key"

    def fail(*args):
        raise llm.VoiceFailed("refusal")

    monkeypatch.setattr(llm, "extract", fail)
    response = world.client(world.doctor_a).post(URL, {"form": "patient", "text": "abc"}, format="json")
    assert response.status_code == 502
    assert "abc" not in response.content.decode()


def test_monthly_limit(world, model, settings):
    model({"full_name": "", "phone_number": "", "birth_date": None, "gender": "", "address": "", "notes": ""})
    settings.VOICE_MONTHLY_LIMIT = 1
    api = world.client(world.doctor_a)
    assert api.post(URL, {"form": "patient", "text": "abc"}, format="json").status_code == 200
    assert api.post(URL, {"form": "patient", "text": "abc"}, format="json").status_code == 429
    # Another branch has its own allowance.
    assert world.client(world.admin_b).post(URL, {"form": "patient", "text": "abc"}, format="json").status_code == 200


def test_needs_one_branch(world, model):
    response = world.client(world.owner, organization=world.org).post(
        URL, {"form": "patient", "text": "abc"}, format="json"
    )
    assert response.status_code == 400
