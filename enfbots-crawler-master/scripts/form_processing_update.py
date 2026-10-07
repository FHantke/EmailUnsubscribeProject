import pandas as pd
from bs4 import BeautifulSoup
from sqlalchemy import text, create_engine

from enfbots_crawler import (
    DBForm,
    RegistrationStatus,
    EmailVerificationStatus,
    DBInput,
    DBWebsite,
    Config,
    DBLabels,
)
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler import PageState, SessionLocal, initialize_base_db


def load_training() -> pd.DataFrame:
    engine = create_engine(f"sqlite:///final_db.sqlite")
    return pd.read_sql(
        text(
            """SELECT
            w.id, w.url, w.reg_url, w.pp_url, w.tc_url,
            w.index_state, w.reg_state, w.pp_state, w.tc_state,
            w.reg_str, w.pp_str, w.tc_str, w.lang, w.annotated, w.crawl_id,
            u.id as uid, u.reg_url as ureg_url, u.pp_url as upp_url, u.tc_url as utc_url,
            u.mark_consent, u.mark_purpose, u.mark_assumed,
            u.ma_checkbox, u.ma_pre_checked, u.ma_forced, u.ma_user,
            u.pp_checkbox, u.pp_pre_checked, u.pp_forced, u.pp_user,
            u.tc_checkbox, u.tc_pre_checked, u.tc_forced, u.tc_user,
            u.comment, u.skipped, u.ra_id
            FROM Website w
            JOIN UserWebsite u ON u.site = w.id
            WHERE u.skipped = 'NOT'"""
        ),
        con=engine,
    )


class FormProcessor:
    def __init__(self, form_code: str):
        self.html = form_code
        soup = BeautifulSoup(form_code, "html.parser", multi_valued_attributes=None)
        self.form = FormBS(tag=soup)

    def process_return_db(self, reg_url) -> DBForm:
        self.form.classify_form()

        db_form = DBForm(
            type=self.form.type,
            multi_stage=False,
            states=[],
            reg_status=RegistrationStatus.UNKNOWN,
            email_verification_status=EmailVerificationStatus.UNKNOWN,
            html=self.html,
        )
        db_form.urls = [reg_url]
        for inp in self.form.inputs:
            db_input = DBInput(
                html_id=inp.id,
                html_tag=inp.tag_name,
                match_string=inp.match_string,
                estimated_type=inp.estimated_type,
                label=inp.label,
                checkbox_prechecked=inp.prechecked,
                is_required=inp.required,
                stage=1,
                content="",
            )
            db_form.inputs.append(db_input)

        return db_form


class SiteProcessor:
    def __init__(self, site_df: pd.Series):
        self.site_df = site_df

    def _get_db_entity(self) -> DBWebsite:
        assert (
            self.site_df["reg_url"] == self.site_df["ureg_url"]
        ), "Website and UserWebsite different"
        assert (
            self.site_df["pp_url"] == self.site_df["upp_url"]
        ), "Website and UserWebsite different"
        assert (
            self.site_df["tc_url"] == self.site_df["utc_url"]
        ), "Website and UserWebsite different"

        db_site = DBWebsite(
            url=self.site_df["url"],
            lang="en",
            index_status=PageState[self.site_df["index_state"]],
            reg_url=self.site_df["reg_url"],
            pp_url=self.site_df["pp_url"],
            tc_url=self.site_df["tc_url"],
            reg_status=RegistrationStatus.SUCCESS_REDIRECT,
        )

        db_labels = DBLabels(
            mark_consent=self.site_df["mark_consent"] == "True",
            mark_purpose=self.site_df["mark_purpose"] == "True",
            ma_checkbox=self.site_df["ma_checkbox"] == "True",
            ma_pre_checked=self.site_df["ma_pre_checked"] == "True",
            ma_forced=self.site_df["ma_forced"] == "True",
            pp_checkbox=self.site_df["pp_checkbox"] == "True",
            pp_pre_checked=self.site_df["pp_pre_checked"] == "True",
            pp_forced=self.site_df["pp_forced"] == "True",
            tc_checkbox=self.site_df["tc_checkbox"] == "True",
            tc_pre_checked=self.site_df["tc_pre_checked"] == "True",
            tc_forced=self.site_df["tc_forced"] == "True",
            tying12=self.hdetect("#tying12"),
            tying13=self.hdetect("#tying13"),
            tying23=self.hdetect("#tying23"),
            tying123=self.hdetect("#tying123"),
            forcedpp=self.hdetect("#forcedpp"),
            forcedtc=self.hdetect("#forcedtc"),
            forcedpptc=self.hdetect("#forcedpptc"),
            colortrick=self.hdetect("#colortrick"),
            colortrick_gr=self.hdetect("#colortrick_gr"),
            colortrick_wr=self.hdetect("#colortrick_wr"),
            colortrick_bw=self.hdetect("#colortrick_bw"),
            hidden=self.hdetect("#hidden"),
            settings=self.hdetect("#settings"),
            age=self.hdetect("#age"),
            credit_card=self.hdetect("#credit_card"),
            phone=self.hdetect("#phone"),
            membership=self.hdetect("#membership"),
            membershipEU=self.hdetect("#membershipEU"),
            other={"comment": self.site_df["comment"]},
        )

        fp = FormProcessor(self.site_df["reg_str"])
        form = fp.process_return_db(self.site_df["reg_url"])
        form.labels = db_labels
        db_site.forms = [form]
        return db_site

    def hdetect(self, key: str) -> bool:
        return key in self.site_df["comment"]

    def store_site(self):
        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            db_website = self._get_db_entity()
            session.add(db_website)


def main():
    initialize_base_db(
        db_url=Config().get_db_url(), alembic_root_dir=Config().code_dir, create=True
    )

    df = load_training()
    df.apply(lambda row: SiteProcessor(row).store_site(), axis=1)


if __name__ == "__main__":
    main()
