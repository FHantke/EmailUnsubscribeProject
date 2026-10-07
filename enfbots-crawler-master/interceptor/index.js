const CDP = require('chrome-remote-interface');
const fs = require("fs");
const captchaStub = require('./captcha-stub')

const [host, port] = process.argv[2].split(":");
const useCaptchaStub = process.argv.length > 3;
let captchaStubBody = null;
if (useCaptchaStub) {
    captchaStubBody = fs.readFileSync(process.argv[3]).toString("utf-8");
}

//const util = require('util');
//const log_file = fs.createWriteStream(__dirname + '/debug.log', {flags : 'w'});
//logg = function(d) { //
//  log_file.write(util.format(d) + '\n');
//};

const snooze = ms => new Promise(resolve => setTimeout(resolve, ms));

function communicate(params) {
    const result = {
        response: {
            error_reason: params.responseErrorReason,
            http_status: params.responseStatusCode,
            headers: {}
        },
        request: {
            url: params.request.url,
            headers: params.request.headers
        }
    };
    if (params.responseHeaders) {
        for (let header of params.responseHeaders) {
            result.response.headers[header.name] = header.value;
        }
    }
    console.log(JSON.stringify(result));
}

async function run() {
    let client;
    try {
        // connect to endpoint
        client = await CDP({
            host, port
        });
        // extract domains
        const {Fetch} = client;
        // setup handlers
        Fetch.requestPaused(async (params) => {
            //logg(params);
            try {
                if ("responseStatusCode" in params || "responseErrorReason" in params) {
                    // request coming back with response
                    communicate(params)
                    await Fetch.continueResponse({
                        requestId: params.requestId,
                    });
                    return;
                }

                // outgoing request
                if (useCaptchaStub) {
                    res = captchaStub.generateResponse(params, captchaStubBody);
                }

                if (res) {
                    communicate({...params, ...res});
                    await Fetch.fulfillRequest(res);
                } else {
                    await Fetch.continueRequest({
                        requestId: params.requestId,
                        interceptResponse: true
                    });
                }
            } catch (e) {
                console.error(e);
            }
        });
        // enable events then start!
        await Fetch.enable();
        while (true) {
            await snooze(10000);
        }
    } catch (err) {
        console.error(err);
    } finally {
        if (client) {
            await client.close();
        }
    }
}

run();