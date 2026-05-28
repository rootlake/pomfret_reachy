async function simulateBoo() {
    const status = document.getElementById("status");
    status.textContent = "Triggering hide…";
    try {
        const resp = await fetch("/boo", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
        });
        if (!resp.ok) throw new Error(await resp.text());
        status.textContent = "Hide queued — then knock head 3× gently or tap Simulate wake.";
    } catch (e) {
        status.textContent = "Error: " + e;
        console.error(e);
    }
}

async function simulateWake() {
    const status = document.getElementById("status");
    status.textContent = "Triggering wake…";
    try {
        const resp = await fetch("/wake", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
        });
        if (!resp.ok) throw new Error(await resp.text());
        status.textContent = "Wake queued.";
    } catch (e) {
        status.textContent = "Error: " + e;
        console.error(e);
    }
}

document.getElementById("boo-btn").addEventListener("click", () => {
    simulateBoo();
});

document.getElementById("wake-btn").addEventListener("click", () => {
    simulateWake();
});
