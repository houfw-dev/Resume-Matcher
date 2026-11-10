"""Service tests for cover letter generation (LLM mocked)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.ai_limits import MAX_JOB_CHARACTERS
from app.services.cover_letter import (
    _is_valid_title,
    generate_cover_letter,
    generate_outreach_message,
    generate_resume_title,
)


@pytest.fixture
def resume_data() -> dict:
    return {
        "personalInfo": {"name": "Jane Doe", "title": "Backend Engineer"},
        "summary": "Backend engineer with 6 years of Python experience.",
        "workExperience": [
            {
                "title": "Senior Backend Engineer",
                "company": "Acme",
                "description": ["Built APIs serving 50K requests/day"],
            }
        ],
    }


class TestGenerateCoverLetter:
    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_empty_jd_uses_resume_only_prompt(
        self, mock_complete: AsyncMock, resume_data: dict
    ) -> None:
        mock_complete.return_value = "  Dear team,\n\nA concise letter.  "

        result = await generate_cover_letter(resume_data, "", "en")

        assert result == "Dear team,\n\nA concise letter."
        prompt = mock_complete.await_args.kwargs["prompt"]
        # The no-JD template never renders a job-description section.
        assert "Job Description:" not in prompt
        assert "Backend engineer with 6 years" in prompt
        assert "English" in prompt

    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_whitespace_jd_treated_as_missing(
        self, mock_complete: AsyncMock, resume_data: dict
    ) -> None:
        mock_complete.return_value = "Letter"

        await generate_cover_letter(resume_data, "   \n  ", "zh")

        prompt = mock_complete.await_args.kwargs["prompt"]
        assert "Job Description:" not in prompt
        assert "Chinese" in prompt or "中文" in prompt

    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_provided_jd_uses_jd_prompt(
        self, mock_complete: AsyncMock, resume_data: dict
    ) -> None:
        mock_complete.return_value = "Letter"

        await generate_cover_letter(resume_data, "We need FastAPI and ETL.", "en")

        prompt = mock_complete.await_args.kwargs["prompt"]
        assert "We need FastAPI and ETL." in prompt
        assert "Job Description:" in prompt

    @patch("app.services.cover_letter.load_config_file")
    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_custom_prompt_used_when_jd_provided(
        self,
        mock_complete: AsyncMock,
        mock_load_config: AsyncMock,
        resume_data: dict,
    ) -> None:
        mock_load_config.return_value = {
            "cover_letter_prompt": (
                "Custom: {job_description} | {resume_data} | {output_language}"
            )
        }
        mock_complete.return_value = "Custom letter"

        result = await generate_cover_letter(resume_data, "Some JD", "en")

        assert result == "Custom letter"
        prompt = mock_complete.await_args.kwargs["prompt"]
        assert prompt.startswith("Custom: Some JD")

    async def test_oversized_jd_rejected(self, resume_data: dict) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            await generate_cover_letter(
                resume_data, "x" * (MAX_JOB_CHARACTERS + 1), "en"
            )


class TestGenerateOutreach:
    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_empty_jd_uses_resume_only_prompt(
        self, mock_complete: AsyncMock, resume_data: dict
    ) -> None:
        mock_complete.return_value = "  Hello, quick intro.  "

        result = await generate_outreach_message(resume_data, "", "en")

        assert result == "Hello, quick intro."
        prompt = mock_complete.await_args.kwargs["prompt"]
        # The no-JD template never renders a job-description section.
        assert "Job Description:" not in prompt
        assert "Backend engineer with 6 years" in prompt
        assert "English" in prompt

    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_whitespace_jd_treated_as_missing(
        self, mock_complete: AsyncMock, resume_data: dict
    ) -> None:
        mock_complete.return_value = "Message"

        await generate_outreach_message(resume_data, "  \n ", "zh")

        prompt = mock_complete.await_args.kwargs["prompt"]
        assert "Job Description:" not in prompt

    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_provided_jd_uses_jd_prompt(
        self, mock_complete: AsyncMock, resume_data: dict
    ) -> None:
        mock_complete.return_value = "Message"

        await generate_outreach_message(
            resume_data, "We need FastAPI and ETL.", "en"
        )

        prompt = mock_complete.await_args.kwargs["prompt"]
        assert "We need FastAPI and ETL." in prompt
        assert "Job Description:" in prompt

    async def test_oversized_jd_rejected(self, resume_data: dict) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            await generate_outreach_message(
                resume_data, "x" * (MAX_JOB_CHARACTERS + 1), "en"
            )


# The exact failure observed in production: a reasoning model spent its whole
# 60-token budget paraphrasing the request and the preamble got stored.
BAD_PREAMBLE = (
    "The user wants extraction of job title and company name, output in "
    "Chinese (Simplified). The user wants extraction of job title"
)


class TestGenerateResumeTitle:
    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_valid_title_returned_on_first_call(
        self, mock_complete: AsyncMock
    ) -> None:
        mock_complete.return_value = '  "高级Java工程师 @ 某科技"  '

        result = await generate_resume_title("Java 岗位 JD", "zh")

        assert result == "高级Java工程师 @ 某科技"
        assert mock_complete.call_count == 1

    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_preamble_triggers_strict_retry_and_succeeds(
        self, mock_complete: AsyncMock
    ) -> None:
        mock_complete.side_effect = [BAD_PREAMBLE, "高级Java工程师 @ 某科技"]

        result = await generate_resume_title("Java 岗位 JD", "zh")

        assert result == "高级Java工程师 @ 某科技"
        assert mock_complete.call_count == 2
        retry_prompt = mock_complete.await_args_list[1].kwargs["prompt"]
        assert "CRITICAL REMINDER" in retry_prompt
        # The retry gets a larger budget so preamble + title can both fit.
        assert mock_complete.await_args_list[1].kwargs["max_tokens"] == 120

    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_preamble_twice_falls_back_to_localized_title(
        self, mock_complete: AsyncMock
    ) -> None:
        mock_complete.side_effect = [BAD_PREAMBLE, BAD_PREAMBLE]

        assert await generate_resume_title("Java 岗位 JD", "zh") == "定制简历"
        assert mock_complete.call_count == 2

    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_english_fallback_when_language_unknown(
        self, mock_complete: AsyncMock
    ) -> None:
        mock_complete.side_effect = [BAD_PREAMBLE, BAD_PREAMBLE]

        assert await generate_resume_title("JD", "xx") == "Tailored Resume"

    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_multiline_response_salvages_valid_line_without_retry(
        self, mock_complete: AsyncMock
    ) -> None:
        mock_complete.return_value = (
            "好的，以下是为您提取的标题：\n高级Java工程师 @ 某科技"
        )

        result = await generate_resume_title("JD", "zh")

        assert result == "高级Java工程师 @ 某科技"
        assert mock_complete.call_count == 1

    @patch("app.services.cover_letter.complete", new_callable=AsyncMock)
    async def test_chinese_preamble_also_retried(
        self, mock_complete: AsyncMock
    ) -> None:
        mock_complete.side_effect = [
            "用户想要从职位描述中提取岗位名称和公司名称",
            "资深架构师 @ 招商云",
        ]

        result = await generate_resume_title("JD", "zh")

        assert result == "资深架构师 @ 招商云"
        assert mock_complete.call_count == 2

    async def test_oversized_jd_rejected(self) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            await generate_resume_title(
                "x" * (MAX_JOB_CHARACTERS + 1), "en"
            )


class TestTitleValidator:
    def test_observed_preamble_rejected(self) -> None:
        assert not _is_valid_title(BAD_PREAMBLE)

    def test_chinese_preamble_rejected(self) -> None:
        assert not _is_valid_title("以下是为您提取的标题：")
        assert not _is_valid_title("用户想要提取岗位名称")

    def test_multiline_rejected(self) -> None:
        assert not _is_valid_title("高级Java工程师\n某科技")

    def test_clean_titles_accepted(self) -> None:
        assert _is_valid_title("高级Java工程师 @ 某科技")
        assert _is_valid_title("Senior Frontend Engineer @ Stripe")
        assert not _is_valid_title("")
