window.addEventListener('DOMContentLoaded', function () {
    document.getElementById("button").addEventListener("click", function (e) {
        e.preventDefault()
        grecaptcha.ready(function () {
            grecaptcha.execute(window.mysitekey, {action: "submit_action"}).then(function (token) {
                document.getElementById("resp").value = token;
                document.getElementById("formid").submit();
            });
        });
    });
    document.getElementById("fake-button").addEventListener("click", function (e) {
        e.preventDefault()
        grecaptcha.ready(function () {
            grecaptcha.execute(window.mysitekey, {action: "fake_action"}).then(function (token) {
                console.log(token);
            });
        });
    });
});