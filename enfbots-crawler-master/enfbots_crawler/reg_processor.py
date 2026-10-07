"""
All browsing activities of the enfbots_crawler are defined here (focus on the registration form)
"""

from __future__ import annotations

import logging
from pathlib import Path
from time import sleep

# Libs
from typing import Optional

# Imports from the enfbots library
from enfbots_crawler.languages import KeywordType, Language

from enfbots_crawler import (
    CaptchaType,
    FormType,
    ExtraStatus,
    RegistrationStatus,
    FormStatus,
)
from enfbots_crawler import PageState, EmailVerificationStatus
from enfbots_crawler.browser import EnfbotsBrowser
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.database import DBForm, DBInput
from enfbots_crawler.form_selenium import FormSelenium
from enfbots_crawler.mail_processor import Sybil, SybilException
from enfbots_crawler.text_lib import extract_text_from_html

logger = logging.getLogger("enfbots_crawler")


class RegProcessor:
    def __init__(
        self,
        browser: EnfbotsBrowser,
        lang: Language,
        credentials: Credentials,
        output_directory: Path,
        index: int = 0,
        is_insecure: Optional[bool] = None,
    ) -> None:
        self.forms: list[FormSelenium] = []
        self.states: set[FormStatus] = set()
        self.br = browser
        self.output_dir = output_directory
        self.index = index
        self.credentials = credentials
        self.lang = lang
        self.sybil = Sybil()
        self.sybil.create_mail_address(self.credentials)

        self.is_insecure = is_insecure

        self.base_url = self.br.current_url
        self.handling_url = self.br.current_url

        self.blocked_submit_state_keywords: list[str] = []

        self.multistage_it = 0

        self.registration_status = RegistrationStatus.UNKNOWN
        self.email_verification_status = EmailVerificationStatus.UNKNOWN

    def handle_registration(self, form: FormSelenium) -> RegistrationStatus:
        self.registration_status = self._form_handle(form)
        return self.registration_status

    def _form_handle(
        self, form: FormSelenium, second_pass: bool = False, email_form: bool = False
    ) -> RegistrationStatus:
        """
        Handle parallel executing of form fill_out and captcha_solving
        :return:
        """
        self.multistage_it += 1
        if self.multistage_it > 5:
            logger.warning("Maximal number of iterations for multi-stage form reached, stopping")
            return RegistrationStatus.FAILURE_SAME_FORM
        self.br.execute_script(
            "arguments[0].setAttribute('data-crawler-form', 'data-crawler-form');", form.tag
        )

        if email_form:
            filename = f"form_{self.index}_email"
        else:
            filename = f"form_{self.index}_stage_{len(self.forms)}"

        self.br.full_dump(self.output_dir, filename)
        self.forms.append(form)
        if second_pass:
            self.forms[-1] = form

        # save the current url temporarily to check for redirects
        # since form handle can be called multiple times we cannot depend on the one in the constructor
        self.handling_url = self.br.current_url

        self._load_submit_success_keywords()

        form.fill_form(self.credentials, second_pass)

        self.br.full_dump(self.output_dir, filename + "_fill")

        submit_state = form.submit_form(js_submit=second_pass)
        self.states.update(submit_state)

        self.br.full_dump(self.output_dir, filename + "_submit")

        state, new_form = self._check_submission_success(form)
        if (
            state == RegistrationStatus.FAILURE_SAME_FORM
            and new_form
            and not second_pass
            and not email_form
        ):
            logger.info("Trying to resubmit form with half_required inputs")
            self.states.add(ExtraStatus.SUBMIT_HALF_REQUIRED)
            return self._form_handle(new_form, True)

        self.states.add(state)
        if state == RegistrationStatus.MULTI_STAGE_FORM and new_form and not email_form:
            logger.info("Trying submit next stage of reg form")
            return self._form_handle(new_form)

        return state

    def verify_email(self) -> EmailVerificationStatus:
        # to make the function look nicer
        try:
            self.email_verification_status = self._verify_email()
        except SybilException as e:
            logger.exception("Unable to access Sybilmail: %s", e)
            self.email_verification_status = EmailVerificationStatus.FAILURE_REACHING_SYBILMAIL
        return self.email_verification_status

    def _verify_email(self) -> EmailVerificationStatus:
        mails = self.sybil.poll(self.credentials, language=self.lang.code)
        if mails:
            # there might be more so we check them all
            for mail in mails:
                if mail.activation_link:
                    logger.info(
                        "Activating the account by visiting the activation link %s",
                        mail.activation_link,
                    )
                    state = self.br.load_page(mail.activation_link)
                    if state == PageState.OK:
                        return self._check_confirmation_success()
                    logger.info("Activation failed")
                    return EmailVerificationStatus.FAILURE_ACTIVATION
                elif mail.verification_code:
                    logger.info("Received verification code: %s", mail.verification_code)

                    for form in self.br.find_forms(self.lang):
                        typ = form.classify_form(allow_verification=True)
                        if typ == FormType.VERIFICATION:
                            logger.info("Detected corresponding mail verification form")
                            self.credentials.verify_code = mail.verification_code
                            form_sel = FormSelenium.from_bs(self.br, form)
                            verification_state = self._form_handle(form_sel, email_form=True)
                            # TODO which is better
                            # if state in (FormStatus.SUCCESS_REDIRECT, FormStatus.SUCCESS_KEYWORDS)
                            if verification_state != RegistrationStatus.FAILURE_SAME_FORM:
                                logger.info("Code verification successful")
                                return EmailVerificationStatus.SUCCESS_VERIFICATION_CODE
                            logger.info("Code verification failed")
                            return EmailVerificationStatus.FAILURE_VERIFICATION_CODE
            return EmailVerificationStatus.SUCCESS_RECEIVED_EMAIL
        return EmailVerificationStatus.FAILURE_NO_EMAIL

    def _load_submit_success_keywords(self) -> None:
        """
        Disabled keywords which appear on the registration page prior to submit the form
        :return:
        """
        page_text = extract_text_from_html(self.br.get_soup()).lower()

        # Success and Failure Keywords
        for keyword in self.lang.get_keywords(KeywordType.SUBMIT_SUCCESS):
            if keyword.text in page_text:
                self.blocked_submit_state_keywords.append(keyword.text)
                logger.info("disable keyword %s for success detection", keyword)

    def _check_submission_success(
        self, form: FormSelenium
    ) -> tuple[RegistrationStatus, Optional[FormSelenium]]:
        """
        Check if submission was successful
        :return: boolean signalizes, if registration was successful
        """

        sleep(1)  # wait until page is fully loaded

        # check if reg form disappeared
        logger.info("checking for registration forms")

        forms = self.br.find_forms(self.lang)
        if forms:
            scores = [form.form_bs.equality_score(f) for f in forms]
            best_form, score = min(zip(forms, scores), key=lambda x: x[1])
            if score < 3:
                logger.info("Same form encountered")
                return RegistrationStatus.FAILURE_SAME_FORM, FormSelenium.from_bs(
                    self.br, best_form
                )

            # reclassify by allowing register forms to be mail less and verification codes to be matches
            for f in forms:
                f.type = f.classify_form(True)

            verification_forms = [f for f in forms if f.type == FormType.VERIFICATION]
            if verification_forms:
                logger.info("Verification form found")
                return RegistrationStatus.VERIFICATION_CODE_REQUESTED, None

            reg_forms = [f for f in forms if f.type == FormType.REGISTER]
            if reg_forms:
                logger.info("New form detected, assuming multi-stage")
                best_form = max(reg_forms, key=lambda x: sum(x.input_counts.values()))
                return RegistrationStatus.MULTI_STAGE_FORM, FormSelenium.from_bs(self.br, best_form)

        # check success by keyword detection
        page_text = extract_text_from_html(self.br.get_soup()).lower()

        # Success Keywords
        for keyword in self.lang.get_keywords(KeywordType.SUBMIT_SUCCESS):
            if keyword.text in page_text and keyword.text not in self.blocked_submit_state_keywords:
                logger.info("success keyword %s found", keyword.text)
                return RegistrationStatus.SUCCESS_KEYWORDS, None

        # check after-registration redirect
        old_url = self.handling_url
        new_url = self.br.current_url

        if old_url != new_url:
            # TODO is this really success? Really bad metric, skews results hard
            logger.info("SUCCESS: redirect detected from %s to %s", old_url, new_url)
            return RegistrationStatus.SUCCESS_REDIRECT, None

        # Failure Keywords
        for keyword in self.lang.get_keywords(KeywordType.SUBMIT_FAILURE):
            if keyword.text in page_text and keyword.text not in self.blocked_submit_state_keywords:
                logger.info("FAILURE: submit failed keyword: '%s' found", keyword)
                return RegistrationStatus.FAILURE_KEYWORDS, None

        return RegistrationStatus.UNKNOWN, None

    def _check_confirmation_success(self) -> EmailVerificationStatus:
        # check success by keyword detection
        page_text = extract_text_from_html(self.br.get_soup())

        success_counter = 0
        # Success Keywords
        for keyword in self.lang.get_keywords(KeywordType.CONFIRM_SUCCESS):
            if keyword.text in page_text:
                logger.info("Success activation keyword %s found", keyword.text)
                success_counter += 1
        # Failure Keywords
        for keyword in self.lang.get_keywords(KeywordType.CONFIRM_FAILURE):
            if keyword.text in page_text:
                logger.info("Failure activation keyword %s found", keyword.text)
                success_counter -= 1

        logger.info("Activation keyword score %s", success_counter)
        if success_counter > 0:
            return EmailVerificationStatus.SUCCESS_ACTIVATION
        elif success_counter < 0:
            return EmailVerificationStatus.FAILURE_LINK_FAIL_KEYWORD
        else:
            return EmailVerificationStatus.FAILURE_LINK_NO_KEYWORD

    def get_db_form(self) -> DBForm:
        main_form = self.forms[0]

        db_form = DBForm(
            type=main_form.form_type,
            multi_stage=len(self.forms) > 1,
            html=main_form.html,
            states=[s.name for s in self.states],
            reg_status=self.registration_status,
            email_verification_status=self.email_verification_status,
            is_insecure=self.is_insecure,
        )

        urls = []
        for i, form in enumerate(self.forms):
            if form.captcha_solver.captcha_type != CaptchaType.NONE:
                db_form.captcha_type = form.captcha_solver.captcha_type
            urls.append(form.url.to_text())
            for inp in form.inputs:
                db_input = DBInput(
                    html_id=inp.bs.id,
                    html_tag=inp.html_tag,
                    match_string=inp.bs.match_string,
                    estimated_type=inp.type,
                    label=inp.bs.label,
                    checkbox_prechecked=inp.prechecked,
                    is_required=inp.required,
                    stage=i,
                    content=inp.content,
                )
                db_form.inputs.append(db_input)

        db_form.urls = str(urls)

        return db_form
