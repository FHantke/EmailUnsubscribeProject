(function () {
    const textarea_recaptcha = '<textarea name="g-recaptcha-response" class="g-recaptcha-response mock-captcha" style="display: none;"></textarea>';
    const textarea_hcaptcha = '<textarea name="h-captcha-response" class="h-captcha-response mock-captcha" style="display: none;"></textarea>';


    const captcha_stub = {
        stub: true,
        is_enterprise: "{{enterprise}}" === "true",
        type: "{{type}}",
        parameters: {},
        initParams: {
            onload: "{{onload}}",
            render: "{{render}}",
            hl: "{{hl}}",
            recaptcha_compat: "{{recaptchacompat}}"
        },
        inputs: [],
        version: "v2",
        actionQueue: [],
        response: null,
        responseMap: new Map(),
        h_id: 0,
        g_id: 0,

        collect_parameters: function () {
            // cannot return all since Selenium does not understand functions...
            params = {
                "sitekey": this.parameters["sitekey"],
                "size": this.parameters["size"]
            }
            console.log("captcha params collected:", params);
            return params
        },

        get_action_queue: function () {
            return this.actionQueue.map(value => value[0]);
        },

        render: function (container, parameters) {
            for (const [key, value] of Object.entries(parameters)) {
                this.parameters[key] = value;
            }

            if (typeof container === "string") {
                container = document.getElementById(container);
            }
            if (container) {
                this._insert_textareas(container, "afterbegin").forEach(a => this.inputs.push(a));
            }
        },
        reset: function (widget_id) {
            console.log("resetting captcha widgets")
        },
        getResponse: function () {
            return this.response;
        },
        setResponse: function (response, action) {
            console.log("received captcha response", response, action)

            if (action) {
                //v3
                this.responseMap.set(action, response);
                const mine = this.actionQueue.filter(x => x[0] === action);
                this.actionQueue = this.actionQueue.filter(x => x[0] !== action);
                for (const [action, callback, input] of mine) {
                    if (input) {
                        input.value = response;
                    }
                    this._call_function(callback, response)
                }
            } else {
                //v2
                this.response = response;
                for (const i of this.inputs) {
                    i.value = response;
                }
                this._call_function(this.parameters["callback"], response);
            }
        },

        // v3
        ready: function (fnc) {
            // our captcha is ready as soon as this script is loaded
            fnc();
        },
        execute: function (site_key, params) {
            const action = params?.action;
            if (action) {
                console.log("Executing action", action)
                if (this.responseMap.has(action)) {
                    return Promise.resolve(this.responseMap.get(action));
                }
                return new Promise(resolve => {
                    this.actionQueue.push([action, resolve, null]);
                });
            }
        },
        _call_function(func, arg) {
            if (func) {
                if (typeof func === "function") {
                    func(arg);
                }
                if (typeof func === "string" && typeof window[func] === "function") {
                    window[func](arg);
                }
            }
        },
        _insert_textareas(container, where) {
            const areas = [];
            if (!(this.type === "hcaptcha" && this.initParams.recaptcha_compat === "off")) {
                container.insertAdjacentHTML(where, textarea_recaptcha);
                if (where === "afterbegin") {
                    areas.push(container.firstElementChild);
                } else if (where === "beforebegin") {
                    areas.push(container.previousElementSibling);
                }
                let id = "g-captcha-response"
                if (this.g_id > 0) {
                    id += "-" + id;
                }
                this.g_id += 1;
                areas[areas.length - 1].id = id;
            }
            if (this.type === "hcaptcha") {
                container.insertAdjacentHTML(where, textarea_hcaptcha);
                if (where === "afterbegin") {
                    areas.push(container.firstElementChild);
                } else if (where === "beforebegin") {
                    areas.push(container.previousElementSibling);
                }
                let id = "h-captcha-response"
                if (this.h_id > 0) {
                    id += "-" + id;
                }
                this.h_id += 1;
                areas[areas.length - 1].id = id;
            }
            return areas;
        },
        load: function () {
            if (window.captcha_stub_loaded) {
                console.log("Stub already loaded");
                return;
            }
            window.captcha_stub_loaded = true;
            const render = this.initParams.render;
            if (render && render.length === 40) {
                this.version = "v3"
                this.parameters["sitekey"] = render;
            }
            this._call_function(this.initParams.onload)
            const objects = document.querySelectorAll(".g-recaptcha,.h-captcha");
            for (const object of objects) {
                const params = new Map(object.getAttributeNames().filter(n => n.startsWith("data-")).map(n => [n.substr(5), object.getAttribute(n)]));
                if (params.has("action") && params.has("sitekey")) {
                    this.version = "v3";
                    this.parameters["sitekey"] = params.get("sitekey");
                    const areas = this._insert_textareas(object, "beforebegin");
                    const action = params.get("action");
                    const callback = params.get("callback");
                    object.addEventListener("click", e => {
                        e.preventDefault()
                        this.actionQueue.push([action, callback, areas[0]]);
                    });
                } else {
                    this._insert_textareas(object, "afterbegin").forEach(a => this.inputs.push(a));
                    for (const [key, value] of params) {
                        this.parameters[key] = value;
                    }
                }
            }
            console.log("Captcha load:", this);
        }
    };

    if (!window.captcha_stub_setup) {
        window.captcha_stub_setup = true;
        window.captcha_stub = captcha_stub;
        // enterprise follows the same API
        // hcaptcha also provides grecaptcha object for compat
        if (captcha_stub.type === "recaptcha") {
            if (captcha_stub.is_enterprise) {
                window.grecaptcha = {
                    enterprise: captcha_stub
                };
            } else {
                window.grecaptcha = captcha_stub;
            }
        } else if (captcha_stub.type === "hcaptcha") {
            window.hcaptcha = captcha_stub
            if (captcha_stub.initParams.recaptcha_compat !== "off") {
                window.grecaptcha = captcha_stub
            }
        }
    }

    if (document.readyState !== "loading") {
        captcha_stub.load();
    } else {
        window.addEventListener('DOMContentLoaded', (event) => {
            captcha_stub.load()
        });
    }
})();


