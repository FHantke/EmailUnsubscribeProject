function b64(originalString) {
    const bufferObj = Buffer.from(originalString, "utf8");
    return bufferObj.toString("base64");
}


function classifyCaptchaType(url) {
    if (!url.hostname || !url.pathname) {
        return null;
    }
    if (url.hostname.endsWith("hcaptcha.com") && url.pathname.includes("api.js")) {
        return "hcaptcha";
    }
    if ((url.hostname.endsWith("recaptcha.net") || url.hostname.endsWith("google.com")) &&
        (url.pathname.includes("recaptcha/api.js")) || url.pathname.includes("recaptcha/enterprise.js")) {
        return "recaptcha";
    }
    return null;
}

function generateResponse(params, body) {

    const {request, requestId} = params;

    const url = new URL(request.url);
    const type = classifyCaptchaType(url);
    if (type == null) {
        return null;
    }

    const enterprise = url.pathname.includes("enterprise.js") ? "true" : "false";
    const query = url.searchParams;
    body = body
        .replace("{{render}}", query.get("render"))
        .replace("{{onload}}", query.get("onload"))
        .replace("{{hl}}", query.get("hl"))
        .replace("{{type}}", type)
        .replace("{{enterprise}}", enterprise);

    return {
        requestId: requestId,
        responseCode: 200,
        responseHeaders: [{
            name: "content-type",
            value: "text/javascript; charset=UTF-8"
        }],
        body: b64(body)
    };
}

exports.classifyCaptchaType = classifyCaptchaType;
exports.generateResponse = generateResponse;