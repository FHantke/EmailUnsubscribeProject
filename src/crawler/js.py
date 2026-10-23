"""JavaScript evaluated in the page. Raw strings so regex backslashes survive."""


# Finds every email signup form in one frame. Run by scan_page() once per frame
# after every phase. Returns one description per form, ranked with the paper's
# rules, and tags each form element with a data-ux-form-id attribute so Python
# can find it again for screenshots.
#
# The numbered sections match section 5 of docs/crawl-flow.md and the diagram in
# docs/detect-js-flow.png:
#   0  settings, and the keyword patterns from config.py (DETECT_PATTERNS)
#   1  collect roots (the page plus every open shadow DOM)
#   -  helpers: walking up the page, visibility, labels, measurements
#   2  is this an email input?          3  top-down detection
#   4  is this a submit button?         4  bottom-up detection
#   5  ranking                          6  tag and measure (describe)
DETECT_JS = r"""
(opts) => {
  // ---- 0. Settings and keyword patterns ---------------------------------------

  // opts comes from Python (detect_options() in browser.py):
  // { prefix, budget, maxShadowScan, patterns }.
  const prefix = opts.prefix;              // start of every data-ux-form-id, e.g. "ux-3"
  const budgetMs = opts.budget;            // stop looking for more forms after this long
  const t0 = Date.now();
  const overBudget = () => Date.now() - t0 > budgetMs;

  // The keyword patterns live in config.py (DETECT_PATTERNS), which explains
  // each one; here they become case-insensitive regular expressions.
  const P = opts.patterns, re = src => new RegExp(src, 'i');
  const EMAIL_HINT = re(P.email);        // an input described like this is an email box ...
  const NOT_EMAIL = re(P.not_email);     // ... unless it is also described like this
  // Form-type rules from config.py FORM_TYPES, in priority order: the first
  // whose detect keys hit, and whose `unless` does not, names the form.
  const TYPES = (opts.formTypes || []).map(t => ({
    name: t.name,
    fields: t.fields || [],
    text: t.text ? re(t.text) : null,
    url: t.url ? re(t.url) : null,
    unless: t.unless ? re(t.unless) : null,
  }));
  const MODAL_HINT = re(P.modal);        // popup-like class/id: ranks first
  const MODAL_HTML = re(P.modal_html);   // last-resort popup check on the form's HTML
  const SUBMIT_HINT = re(P.submit);      // text that makes a short clickable element a submit button
  const CONSENT_HINT = re(P.consent);    // -> consent_text_hint
  // Elements that might be a submit button; isSubmitLike() decides.
  const SUBMIT_SEL = 'button, input[type=submit], input[type=image], input[type=button], [role=button], a, div, span';

  const vw = window.innerWidth, vh = window.innerHeight;   // viewport size in pixels


  // ---- 1. Collect roots ------------------------------------------------------
  // The page plus every open shadow root inside it (sealed-off widget boxes that
  // a normal search does not enter). Stops after opts.maxShadowScan elements.

  const roots = [document];
  let scanned = 0;
  (function collect(root) {
    for (const e of root.querySelectorAll('*')) {
      if (++scanned > opts.maxShadowScan) return;
      if (e.shadowRoot) { roots.push(e.shadowRoot); collect(e.shadowRoot); }
    }
  })(document);

  // querySelectorAll over every root, so later searches also see shadow DOM.
  const qsa = sel => roots.flatMap(r => Array.from(r.querySelectorAll(sel)));


  // ---- Helpers: walking up the page ------------------------------------------

  // The element's parent. At the top of a shadow root, continue from the
  // element that hosts it, so walks up can leave a shadow widget.
  const parentOf = el => {
    if (el.parentElement) return el.parentElement;
    const root = el.getRootNode ? el.getRootNode() : null;
    return root && root.host ? root.host : null;
  };

  // The element itself, then its parent, grandparent, ... (at most `max`).
  const ancestors = (el, max = 60) => {
    const out = [];
    for (let e = el; e && out.length < max; e = parentOf(e)) out.push(e);
    return out;
  };

  // Collapse runs of whitespace and trim.
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();


  // ---- Helpers: visibility ---------------------------------------------------

  // Visible to a person: at least 2x2 px, and no ancestor hidden by
  // display:none, visibility:hidden or opacity:0.
  const isVisible = el => {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    for (const e of ancestors(el)) {
      const s = getComputedStyle(e);
      if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return false;
    }
    return true;
  };


  // ---- 2. Is this an email input? --------------------------------------------

  // Every label an input has: <label for=id>, a wrapping <label>, aria-label,
  // aria-labelledby and title. '' means the input has no label at all.
  const labelText = input => {
    const parts = [];
    const root = input.getRootNode();
    if (input.id && root.querySelectorAll) {
      try {
        root.querySelectorAll('label[for="' + CSS.escape(input.id) + '"]').forEach(l => parts.push(l.innerText));
      } catch (e) {}
    }
    const wrap = input.closest('label');
    if (wrap) parts.push(wrap.innerText);
    parts.push(input.getAttribute('aria-label') || '');
    (input.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean).forEach(id => {
      const n = (root.getElementById && root.getElementById(id)) || document.getElementById(id);
      if (n) parts.push(n.innerText);
    });
    parts.push(input.getAttribute('title') || '');
    return clean(parts.join(' '));
  };

  // All the text that describes an input: its attributes plus its labels.
  const hints = el =>
    ['name', 'id', 'class', 'placeholder', 'value', 'title', 'aria-label', 'autocomplete', 'inputmode']
      .map(a => el.getAttribute(a) || '').join(' ') + ' ' + labelText(el);

  // type="email", or a plain text input described as an email box.
  const isEmailInput = el => {
    if (el.tagName !== 'INPUT') return false;
    const t = (el.getAttribute('type') || 'text').toLowerCase();
    if (t === 'email') return true;
    if (t !== 'text' && t !== '') return false;
    const h = hints(el);
    return EMAIL_HINT.test(h) && !NOT_EMAIL.test(h);
  };


  // ---- 4a. Is this a submit button? ------------------------------------------

  // The text a person sees on a clickable element (at most 80 characters).
  const clickText = el => clean(
    el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt')
  ).slice(0, 80);

  // A visible element that works as a submit button:
  //   - any <button> except type="reset"
  //   - <input type="submit"> or type="image"; type="button" only with submit words
  //   - a short (<=40 chars) link/div/span with at most 2 children, submit words,
  //     and something that makes it clickable (role=button, a link, cursor:pointer)
  const isSubmitLike = el => {
    const tag = el.tagName, type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'BUTTON') return type !== 'reset' && isVisible(el);
    if (tag === 'INPUT') {
      const ok = type === 'submit' || type === 'image' || (type === 'button' && SUBMIT_HINT.test(clickText(el)));
      return ok && isVisible(el);
    }
    if (el.children.length > 2) return false;
    const txt = clickText(el);
    if (!txt || txt.length > 40 || !SUBMIT_HINT.test(txt)) return false;
    const clickable = el.getAttribute('role') === 'button' || tag === 'A' || getComputedStyle(el).cursor === 'pointer';
    return clickable && isVisible(el);
  };


  // ---- Helpers: ranking signals (used in step 5) -----------------------------

  // How far "in front" the form sits: the first z-index set on it or an ancestor.
  const effectiveZ = el => {
    for (const e of ancestors(el)) {
      const z = getComputedStyle(e).zIndex;
      if (z !== 'auto') return parseInt(z, 10) || 0;
    }
    return 0;
  };

  // Looks like a popup: it or one of 10 ancestors is a dialog, or has a
  // popup-like class/id; last resort, "modal"/"dialog" anywhere in its HTML.
  const modalHint = el => {
    for (const e of ancestors(el, 10)) {
      if (e.tagName === 'DIALOG' || e.getAttribute('role') === 'dialog' || e.getAttribute('aria-modal') === 'true') return true;
      if (MODAL_HINT.test((e.getAttribute('class') || '') + ' ' + (e.id || ''))) return true;
    }
    return MODAL_HTML.test(el.outerHTML.slice(0, 20000));
  };

  // The plain text inside `scope`, leaving out links, buttons and scripts, so a
  // sentence like "Log in to Hulu" counts but a "Sign in" menu link does not.
  const plainText = scope => {
    const out = [];
    const walk = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n && out.length < 2000; n = walk.nextNode()) {
      const p = n.parentElement;
      if (p && !p.closest('a, button, [role=button], script, style, noscript, template')) out.push(n.nodeValue);
    }
    return clean(out.join(' ')).slice(0, 20000);
  };

  // What kind of form this is. Every form with an email box is recorded, but
  // many are not signups; this labels them so analysis can filter. Each type is
  // tried in turn against the form's own HTML (attributes included, so
  // class="login-box" counts), the plain text around it, and the page address.
  const formType = (el, scope) => {
    const html = el.outerHTML.slice(0, 20000);
    const near = plainText(scope);
    const addr = location.hostname + location.pathname;
    for (const t of TYPES) {
      // A field is hard evidence (a password box really is a login) and ignores
      // `unless`; wording and the page address are softer and can be cancelled.
      if (t.fields.some(f => el.querySelector('input[type=' + f + ']'))) return t.name;
      const soft = (t.text && (t.text.test(html) || t.text.test(near)))
        || (t.url && t.url.test(addr));
      if (soft && !(t.unless && (t.unless.test(html) || t.unless.test(near)))) return t.name;
    }
    return opts.defaultFormType;
  };


  // ---- Helpers: where the form is (used in step 6) ---------------------------

  // The nearest ancestor that is position:fixed or sticky (popups, sticky bars).
  const fixedAncestor = el => {
    for (const e of ancestors(el)) {
      const p = getComputedStyle(e).position;
      if (p === 'fixed' || p === 'sticky') return { el: e, position: p };
    }
    return null;
  };

  // The page region the form is in: footer, header (incl. nav), sidebar, article.
  const landmark = el => {
    for (const e of ancestors(el)) {
      const t = e.tagName, role = e.getAttribute('role');
      if (t === 'FOOTER' || role === 'contentinfo') return 'footer';
      if (t === 'HEADER' || t === 'NAV' || role === 'banner' || role === 'navigation') return 'header';
      if (t === 'ASIDE' || role === 'complementary') return 'sidebar';
      if (t === 'ARTICLE') return 'article';
    }
    return null;
  };

  // Share of the viewport the form covers, 0 to 1.
  const coverage = rect => (Math.min(rect.width, vw) * Math.min(rect.height, vh)) / (vw * vh);

  // placement_guess. Fixed elements: covers >50% -> fullscreen_takeover; a full-width
  // strip <=180px tall -> sticky_bar_top/bottom; centred -> modal_popup; else slide_in.
  // Otherwise: sticky_inline, the landmark, near_page_bottom (lowest 15%), in_article or inline.
  const placement = (rect, fx, lm) => {
    if (fx && fx.position === 'fixed') {
      const fr = fx.el.getBoundingClientRect();
      if (coverage(rect) > 0.5) return 'fullscreen_takeover';
      if (fr.width >= vw * 0.9 && fr.height <= 180) return fr.top < vh / 2 ? 'sticky_bar_top' : 'sticky_bar_bottom';
      const centered = Math.abs(rect.left + rect.width / 2 - vw / 2) < vw * 0.12;
      return centered ? 'modal_popup' : 'slide_in';
    }
    if (fx && fx.position === 'sticky') return 'sticky_inline';
    if (lm === 'footer' || lm === 'header' || lm === 'sidebar') return lm;
    const docH = Math.max(document.documentElement.scrollHeight, 1);
    if ((rect.top + window.scrollY) / docH > 0.85) return 'near_page_bottom';
    return lm === 'article' ? 'in_article' : 'inline';
  };

  // The area around the form that is searched for its heading, consent text
  // and "No thanks" buttons: the whole popup if the form is in one,
  // else the form's parent (but never <body>, and never outside a shadow widget).
  const scopeFor = (el, fx) => {
    if (fx && fx.position === 'fixed') return fx.el;
    const p = parentOf(el);
    if (!p || p === document.body || p === document.documentElement) return el;
    if (p.getRootNode() !== el.getRootNode()) return el;  // stay inside a shadow widget
    return p;
  };

  // The first visible heading (or title-/heading-/headline-classed element) in the scope.
  const headingIn = scope => {
    const h = Array.from(scope.querySelectorAll('h1,h2,h3,h4,h5,h6,[class*="title"],[class*="heading"],[class*="headline"]'))
      .find(n => clean(n.innerText) && isVisible(n));
    return h ? clean(h.innerText).slice(0, 200) : '';
  };


  // ---- Helpers: the form's fields --------------------------------------------

  // The fields a person fills in: visible inputs/selects/textareas, plus every
  // checkbox and radio (often styled invisible), minus hidden inputs and buttons.
  // Returns them grouped, with `types` and `names` in matching order:
  // text-like fields, then checkboxes, then one entry per radio group.
  const fieldInfo = el => {
    const typeOf = f => f.tagName === 'INPUT' ? (f.getAttribute('type') || 'text').toLowerCase() : f.tagName.toLowerCase();
    const fields = Array.from(el.querySelectorAll('input, select, textarea')).filter(f => {
      const t = typeOf(f);
      if (['hidden', 'submit', 'button', 'image', 'reset'].includes(t)) return false;
      return t === 'checkbox' || t === 'radio' || isVisible(f);
    });
    const checkboxes = fields.filter(f => typeOf(f) === 'checkbox');
    const radioGroups = new Set(fields.filter(f => typeOf(f) === 'radio').map(f => f.name || f.id));
    const textLike = fields.filter(f => !['checkbox', 'radio'].includes(typeOf(f)));
    const types = textLike.map(typeOf).concat(checkboxes.map(() => 'checkbox'), Array.from(radioGroups).map(() => 'radio_group'));
    // Same order as `types`: the name attribute, else the id, else ''. A radio group's name is the group's.
    const nameOf = f => f.getAttribute('name') || f.id || '';
    const names = textLike.map(nameOf).concat(checkboxes.map(nameOf), Array.from(radioGroups).map(g => g || ''));
    return { checkboxes, textLike, types, names, n: textLike.length + checkboxes.length + radioGroups.size };
  };


  // ---- 3. Top-down detection -------------------------------------------------
  // Every <form> that contains a visible email input is a candidate. Its email
  // inputs are "claimed" so bottom-up does not report the same form again.

  const cands = [];            // { el, method, email } for each form found
  const claimed = new Set();   // email inputs that already belong to a candidate

  qsa('form').forEach(form => {
    if (overBudget()) return;
    const emails = Array.from(form.querySelectorAll('input')).filter(i => isEmailInput(i) && isVisible(i));
    if (!emails.length) return;
    emails.forEach(e => claimed.add(e));
    cands.push({ el: form, method: 'top-down', email: emails[0] });
  });


  // ---- 4. Bottom-up detection ------------------------------------------------
  // For each email input not claimed above (in practice: outside any <form>),
  // climb up at most 15 levels, stopping at <body>, to the first element that
  // also contains a submit button. That element is the candidate.

  qsa('input').forEach(inp => {
    if (overBudget()) return;
    if (claimed.has(inp) || !isEmailInput(inp) || !isVisible(inp)) return;
    let c = parentOf(inp), found = null;
    for (let depth = 0; c && depth < 15; depth++, c = parentOf(c)) {
      if (c === document.body || c === document.documentElement) break;
      const btns = Array.from(c.querySelectorAll(SUBMIT_SEL)).slice(0, 300);
      if (btns.some(b => b !== inp && isSubmitLike(b))) { found = c; break; }
    }
    if (!found) return;
    found.querySelectorAll('input').forEach(i => claimed.add(i));   // one candidate per widget
    claimed.add(inp);
    cands.push({ el: found, method: 'bottom-up', email: inp });
  });


  // ---- 5. Ranking ------------------------------------------------------------
  // The paper's rules, each used only to break ties in the ones before it:
  //   higher z-index first -> popup-looking first -> login forms last -> more fields first.

  cands.forEach(r => {
    r.fi = fieldInfo(r.el);
    r.z = effectiveZ(r.el);
    r.modal = modalHint(r.el);
    r.type = formType(r.el, scopeFor(r.el, fixedAncestor(r.el)));
    r.offTarget = r.type === opts.targetFormType ? 0 : 1;    // anything but a subscription form ranks lower
  });
  cands.sort((a, b) =>
    (b.z - a.z) || (b.modal - a.modal) || (a.offTarget - b.offTarget) || (b.fi.n - a.fi.n));


  // ---- 6. Tag and measure ----------------------------------------------------
  // One description per candidate, in rank order. The keys become forms.csv
  // columns (dom_id, email_name and email_id are used by Python only).

  // Counter shared by every run in this frame, so each form keeps a unique id
  // across phases.
  window.__uxFormSeq = window.__uxFormSeq || 0;

  const describe = (r, i) => {
    const el = r.el, email = r.email, fi = r.fi;
    if (!el.dataset.uxFormId) el.dataset.uxFormId = prefix + '-' + (++window.__uxFormSeq);

    const rect = el.getBoundingClientRect();
    const fx = fixedAncestor(el);
    const scope = scopeFor(el, fx);
    const scopeText = clean(scope.innerText);

    const submits = Array.from(el.querySelectorAll(SUBMIT_SEL)).slice(0, 300).filter(isSubmitLike);
    // Other buttons/links around the form, e.g. "No thanks" or a close button.
    const others = Array.from(scope.querySelectorAll('a, button, [role=button]'))
      .filter(b => !el.contains(b) && isVisible(b))
      .map(b => clickText(b) || '[no accessible text]')
      .slice(0, 6);

    return {
      // which form, and how it was found
      dom_id: el.dataset.uxFormId,
      detection_method: r.method,
      rank_on_page: i + 1,

      // where it is
      placement_guess: placement(rect, fx, landmark(el)),
      z_index: r.z,
      modal_hint: r.modal,
      form_type: r.type,
      in_shadow_dom: el.getRootNode() !== document,

      // its fields
      n_fields: fi.n,
      field_types: fi.types,
      field_names: fi.names,
      n_checkboxes: fi.checkboxes.length,
      n_checkboxes_prechecked: fi.checkboxes.filter(c => c.checked).length,
      fields_missing_label: fi.textLike.filter(f => !labelText(f)).length,

      // its email box
      email_input_type: (email.getAttribute('type') || 'text').toLowerCase(),
      email_has_label: !!labelText(email),
      email_name: email.getAttribute('name') || '',
      email_id: email.id || '',
      email_placeholder: email.getAttribute('placeholder') || '',
      email_autocomplete: email.getAttribute('autocomplete') || '',
      email_required: email.required || email.getAttribute('aria-required') === 'true',

      // the words on and around it
      submit_text: submits.map(clickText).filter(Boolean).slice(0, 3),
      other_clickable_text: others,
      heading: headingIn(scope),
      consent_text_hint: CONSENT_HINT.test(scopeText),

      // its size
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      viewport_coverage: +coverage(rect).toFixed(3),

      form_text: scopeText.slice(0, 600),

      // The elements themselves, for submit.py only (opts.withElements).
      // Selenium turns these into WebElements, which work inside shadow DOM
      // where a [data-ux-form-id] lookup from Python does not. Off during a
      // crawl, so detection sends and receives exactly what it always has.
      ...(opts.withElements ? {
        form_el: el,
        email_el: email,
        text_els: fi.textLike,
        checkbox_els: fi.checkboxes,
        submit_els: submits,
      } : {}),
    };
  };

  return cands.map(describe);
}
"""

# What submit.py needs to know about the fields it was handed: enough to decide
# which are required, what each one is asking for, and what is already in them.
# One call for the whole form, rather than an attribute read per field.
FIELD_INFO_JS = r"""
(els) => els.map(f => ({
  name: f.getAttribute('name') || f.id || '',
  type: (f.tagName === 'INPUT' ? (f.getAttribute('type') || 'text') : f.tagName).toLowerCase(),
  // Either way of marking a field required; some forms only set the ARIA one.
  required: !!(f.required || f.getAttribute('aria-required') === 'true'),
  placeholder: f.getAttribute('placeholder') || '',
  label: ((f.labels && f.labels[0] ? f.labels[0].innerText : '') ||
          f.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 80),
  value: f.value || '',
  checked: !!f.checked,
  // For a <select>: the values it offers, so a required one can be answered.
  options: f.tagName === 'SELECT' ? Array.from(f.options).map(o => o.value) : [],
}))
"""


# Every <a href> on the page, for rank_links() to filter and score.
LINKS_JS = r"""
() => Array.from(document.querySelectorAll('a[href]')).map(a => {
  const r = a.getBoundingClientRect(), s = getComputedStyle(a);
  return {
    // The absolute URL (the browser resolves relative links).
    href: a.href,
    // What a person reads on the link; aria-label/title cover icon-only links.
    text: (a.innerText || a.getAttribute('aria-label') || a.title || '').replace(/\s+/g, ' ').trim().slice(0, 120),
    // Has a size and is not hidden; rank_links() skips invisible links.
    visible: r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none',
  };
})
"""

# Scroll down the page in steps (within budgetMs), always reach the bottom, then return to
# the top. Fires scroll-depth popups and bottom sticky bars for the after_scroll phase.
SCROLL_JS = r"""
async (budgetMs) => {
  const pause = ms => new Promise(r => setTimeout(r, ms));
  const t0 = Date.now();
  const vh = window.innerHeight;
  const docH = () => document.documentElement.scrollHeight;   // re-read: pages grow as they load
  const step = Math.max(200, Math.floor(vh * 0.8));           // 80% of a screen per step

  for (let y = step; y < docH() - vh; y += step) {
    window.scrollTo(0, y);
    await pause(180);
    if (Date.now() - t0 > budgetMs) break;
  }
  window.scrollTo(0, docH());   // always land on the bottom: sticky bars trigger there
  await pause(600);
  window.scrollTo(0, 0);        // back to the top for the next phase
  await pause(400);
}
"""

# The events exit-intent popups listen for: the pointer leaving through the top of the
# window. Paired with a real mouse sweep in simulate_exit_intent().
EXIT_INTENT_JS = r"""
() => {
  // A pointer just above the window (clientY -2), heading nowhere (relatedTarget null).
  const o = { bubbles: true, cancelable: true, clientX: Math.round(innerWidth / 2), clientY: -2, relatedTarget: null, view: window };
  const leave = { ...o, bubbles: false };   // mouseleave never bubbles
  // Sites listen on different elements, so fire on each of them.
  document.dispatchEvent(new MouseEvent('mouseout', o));
  document.documentElement.dispatchEvent(new MouseEvent('mouseout', o));
  document.dispatchEvent(new MouseEvent('mouseleave', leave));
  document.documentElement.dispatchEvent(new MouseEvent('mouseleave', leave));
  if (document.body) document.body.dispatchEvent(new MouseEvent('mouseleave', leave));
}
"""
