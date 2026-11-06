"""Header demographic fields on PersonalInfo.

Chinese resumes state 性别 / 年龄 / 工作年限 / 最高学历 in the header. The upload
parser extracts them into dedicated personalInfo fields (see PARSE_RESUME_PROMPT)
and the parsed payload is canonicalized through ``ResumeData``. These tests pin
both ends: the fields survive the schema round-trip verbatim, and missing values
stay empty strings rather than being rejected or invented.
"""

from app.schemas import ResumeData


def test_demographics_round_trip_through_resume_data() -> None:
    payload = {
        "personalInfo": {
            "name": "王浩",
            "title": "Java 开发工程师",
            "gender": "男",
            "age": "28岁",
            "workYears": "5年",
            "educationLevel": "本科",
        }
    }

    dumped = ResumeData.model_validate(payload).model_dump()

    info = dumped["personalInfo"]
    assert info["gender"] == "男"
    assert info["age"] == "28岁"
    assert info["workYears"] == "5年"
    assert info["educationLevel"] == "本科"


def test_demographics_default_to_empty_strings() -> None:
    dumped = ResumeData.model_validate({"personalInfo": {"name": "Jane"}}).model_dump()

    info = dumped["personalInfo"]
    assert info["gender"] == ""
    assert info["age"] == ""
    assert info["workYears"] == ""
    assert info["educationLevel"] == ""
