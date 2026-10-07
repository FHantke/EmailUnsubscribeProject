import bs4
import pytest
from pathlib import Path

from pytest_mock import MockerFixture

from enfbots_crawler.languages import Language

from enfbots_crawler import InputType
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.input_bs import InputBS

test_login_form = """
<form>
  <div>
      <input class="form-element form-field" id="next" name="j_username" type="text" value="" autofocus="">
  </div>
  <label>Nested label</label>
  <div>
    <div>
      <input class="form-element form-field" id="nested" name="j_username" type="text" value="" autofocus="">
    </div>
  </div>
  <label>Previous label</label>
  <div>
    <input class="form-element form-field" id="previous" name="j_username" type="text" value="" autofocus="" autocomplete="email">
  </div>
  <div>
    <label>Sibiling labeltrap</label>
    <label>Sibiling label</label>
    <input class="form-element form-field" id="sibiling" name="j_username" type="text" value="" autofocus="">
  </div>
  <div>
    <label for="username">ETH username</label>
    <label>fake</label>
    <input class="form-element form-field" id="username" name="j_username" type="text" value="" autofocus="">
    <label>fake</label>
  </div>
  <div>
    <label for="password">ETH password for web applications (LDAP)</label>
    <input class="form-element form-field" id="password" name="j_password" type="password" value="" required>
  </div>
  <div>
    <input type="checkbox" name="donotcache" value="1" id="donotcache" checked>
    <label for="donotcache">Disable 'single sign-on' (on public or shared computers)</label>
   </div>
  <div>
    <input id="_shib_idp_revokeConsent" type="checkbox" name="_shib_idp_revokeConsent" value="true">
    <label for="_shib_idp_revokeConsent">Clear prior granting of permission for release of your information to this service.</label>
  </div>
  <div>
    <button class="btn" type="submit" name="_eventId_proceed">Login</button>
  </div>
</form>
"""


@pytest.fixture
def form(mocker: MockerFixture):
    soup = bs4.BeautifulSoup(test_login_form, "html.parser", multi_valued_attributes=None)
    return mocker.MagicMock(tag=soup.form, lang=Language.get(Path("enfbots_crawler/languages"), "en"))


def test_autocomplete_type(form):
    element = form.tag.find("input", {"id": "previous"})
    el = InputBS(form, element)
    assert el.estimated_type is InputType.MAIL


def test_keyword_match(form):
    element = form.tag.find("input", {"id": "username"})
    el = InputBS(form, element)
    assert el.estimated_type is InputType.USERNAME


def test_for_label(form):
    element = form.tag.find("input", {"id": "username"})
    el = InputBS(form, element)
    assert el.label == "ETH username"


def test_sibiling_label(form):
    element = form.tag.find("input", {"id": "sibiling"})
    el = InputBS(form, element)
    assert el.label == "Sibiling label"


def test_next_label(form):
    element = form.tag.find("input", {"id": "next"})
    el = InputBS(form, element)
    assert el.label == "Nested label"


def test_nested_label(form):
    element = form.tag.find("input", {"id": "nested"})
    el = InputBS(form, element)
    assert el.label == "Nested label"


def test_previous_label(form):
    element = form.tag.find("input", {"id": "previous"})
    el = InputBS(form, element)
    assert el.label == "Previous label"


def test_prechecked(form):
    element = form.tag.find("input", {"id": "donotcache"})
    el = InputBS(form, element)
    assert el.prechecked


def test_required(form):
    element = form.tag.find("input", {"id": "password"})
    el = InputBS(form, element)
    assert el.required


verification_form = """
<div align="center" class="border">
    <div class="header">
        <h1 class="word">Verify email</h1>
    </div></br></br></br>
    <h2 class="word">
        <form action="verify" method="post">
            <input id="code" name="code" type="text" placeholder="Enter the verification code" class="textbox"/></br></br>
            <input id="subm" type="submit" class="btn" value="Submit"></br>
        </form>
    </h2>
</div>
"""


@pytest.fixture
def verify_form(mocker: MockerFixture):
    verify_soup = bs4.BeautifulSoup(verification_form, "html.parser", multi_valued_attributes=None)
    return mocker.MagicMock(tag=verify_soup.form, lang=Language.get(Path("enfbots_crawler/languages"), "en"))


def test_code(verify_form):
    element = verify_form.tag.find("input", {"id": "code"})
    el = InputBS(verify_form, element)
    assert el.estimated_type == InputType.VERIFY_CODE


def test_submit(verify_form):
    element = verify_form.tag.find("input", {"id": "subm"})
    el = InputBS(verify_form, element)
    assert el.estimated_type == InputType.BUTTON_SUBMIT
    assert el.direct_type == InputType.BUTTON_SUBMIT


def parse(html):
    soup = bs4.BeautifulSoup(html, "html.parser", multi_valued_attributes=None)
    return FormBS(soup.form)


def test_blacklist1():
    form = parse(
        """
    <form>
        <div>
            <label for="in2">input</label>
            <input id="in1"/>
            <input id="in2"/>
        </div>
    </form>"""
    )

    assert form.inputs[0].label is None
    assert form.inputs[1].label == "input"


def test_blacklist2():
    form = parse(
        """
    <form>
        <div>
            <input id="in1"/>
            <label>input</label>
            <input id="in2"/>
        </div>
    </form>"""
    )

    assert form.inputs[0].label is None
    assert form.inputs[1].label == "input"


def test_blacklist3():
    form = parse(
        """
    <form>
        <div>
            <input id="in1"/>
            <label>input</label>
            <input id="in2"/>
            <input id="in2"/>
        </div>
    </form>"""
    )

    assert form.inputs[0].label is None
    assert form.inputs[1].label == "input"
    assert form.inputs[2].label is None


def test_fullname():
    form = parse(
        """
        <form>
     <p class="comment-form-author">
      <label for="author">
       Name
       <span class="required">
        *
       </span>
      </label>
      <input class="form-control" id="author" name="author" required="required" size="30" type="text" value=""/>
     </p>
    </form>
        """
    )
    inp = form.inputs[0]
    assert inp.label == "Name *"
    assert inp.required
    assert inp.estimated_type == InputType.FULL_NAME


def test_parent_label_with_sibiling():
    form = parse(
        """
        <form>
          <label>
           Sign up to our newsletter below:
          </label>
          <input name="EMAIL" placeholder="Your email address" required="" type="email"/>
          <input type="submit" value="&gt;"/>
          <label>
           <input name="AGREE_TO_TERMS" required="" type="checkbox" value="1"/>
           By checking this box you agree to our
           <a href="/terms">
            T&amp;Cs
           </a>
          </label>
        </form>
        """
    )
    assert form.inputs[0].label == "Sign up to our newsletter below:"
    assert form.inputs[1].label is None
    assert form.inputs[2].label == "By checking this box you agree to our T&Cs"


def test_first_name():
    form = parse(
        """
        <form>
            <label for="dealer-access-name" class="label">First Name <sup class="required">*</sup></label>
            <input name="member_first_name" id="dealer-access-name" type="text" class="input input_text mix-input_full" value="Tielo Sitz">
        </form>
        """
    )
    assert form.inputs[0].estimated_type == InputType.FIRST_NAME
