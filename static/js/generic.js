function initPage() {
    startWarningCountdown();
    startFailedCountdown();
    document.getElementById("submit-button").addEventListener("click", sendData);
} 

function checkForm() {
    if (!document.getElementById('consent').checked)
    {
        alert('You cannot submit this HIT without giving your explicit consent!');
        return false;
    }
	return true;
}

function validateForm() {
	return checkForm();
}


function collectData() {
    var data = {};

    // FIXME - are there other inputs we would want to capture?  textarea?
    let elements = document.getElementsByTagName("input");
    Array.from(elements).forEach(function (element) {

        // FIXME - this could be cleaner, but checkboxes were returning false for element.hasAttribute("checked") ??
        if (element.hasAttribute("type") && (element.type == "checkbox" || element.type == "radio")) {
            data[element.id] = element.checked;
        } else if (element.hasAttribute("value")) {
            data[element.id] = element.value; 
        } else {
            // TODO - put some real error handling in there, even to alert the dev
            alert("element has no checked or value attributes!");
            alert(element.hasAttribute("checked"));
            alert(element.type);
            alert(element.id);
            alert(element.checked);
            
        }
    });

    return JSON.stringify(data);
}


async function sendData() {
    if (!checkForm()) {
        return; // Do not send data if checkForm() returns false
    }

    const data = collectData();
    const url = "/"; // Replace with your server URL

    try {
        const response = await fetch(url, {
            method: "POST",
            headers: {
            "Content-Type": "application/json",
        },
        body: data,
    });

    if (response.status === 200) {
        const jsonResponse = await response.json();
        console.log("Data sent successfully", jsonResponse);
        alert("We have received your submission. Thank you for your participation!");

        // FIXME - turn this back on
        // window.location.href = "https://app.prolific.co/submissions/complete?cc=12345"; // Replace with your Prolific completion URL
    } else {
        console.log("Failed to send data: " + response.statusText, response.status);
    }
    } catch (error) {
        console.error("There was a problem sending the data", error);
    }
}


    

// This script tag will start a countdown to alert the worker when 50 minutes have passed.
// The worker will have 10 minutes to finish the task before the HIT is automatically submitted.
function startWarningCountdown() {
    var minutes = 50; //var minutes = 50;
    var seconds = 0;
    var totalSeconds = minutes * 60 + seconds;

    var interval = setInterval(function () {
        seconds--;
        if (seconds < 0) {
            minutes--;
            seconds = 59;
        }

        if (minutes < 0) {
            clearInterval(interval);
            alert("50 minutes have passed! You have 10 minutes to finish the task! If you do not finish in time, your answers will not be used and you will not be paid.");
        }
    }, 1000);
}
    function startFailedCountdown() {
    var minutes = 60; //var minutes = 60;
    var seconds = 0;
    var totalSeconds = minutes * 60 + seconds;

    var interval = setInterval(function() {
        seconds--;
        if (seconds < 0) {
            minutes--;
            seconds = 59;
        }

        if (minutes < 0) {

            // Disable the submit button
            document.getElementById("submit-button").disabled = true;
            document.getElementById("submit-button").innerHTML = "You cannot submit this HIT anymore.";
            document.getElementById("submit-button").classList.add("is-danger")

            clearInterval(interval);

            alert("The allocated time for this task has passed. Your answers will not be used and you will not be paid.");

            // Redirect the worker to the Prolific app: https://app.prolific.com/
            window.location.href = "https://app.prolific.co/";

        }
    }, 1000);
}