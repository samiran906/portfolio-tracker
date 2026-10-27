(() => {
    "use strict";

    const configs = [
        {
            key: "nps",
            accountId: 5,
            fields: ["nps-samiran", "nps-sukhada"],
            date: "nps-date",
            total: "nps-total",
            form: "nps-balance-form",
            message: "nps-balance-message",
            button: "save-nps-balance",
            label: "NPS"
        },
        {
            key: "eps",
            accountId: 6,
            fields: ["eps-samiran", "eps-sukhada"],
            date: "eps-date",
            total: "eps-total",
            form: "eps-balance-form",
            message: "eps-balance-message",
            button: "save-eps-balance",
            label: "EPS"
        }
    ];

    const $ = (id) => document.getElementById(id);
    const money = new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });

    function localDate() {
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, "0");
        const day = String(now.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }

    async function request(url, options = {}) {
        const response = await fetch(url, {
            ...options,
            headers: {
                "Content-Type": "application/json",
                ...(options.headers || {})
            }
        });

        let data;
        try {
            data = await response.json();
        } catch {
            data = {};
        }

        if (!response.ok) {
            throw new Error(data.error || `Request failed (${response.status})`);
        }
        return data;
    }

    function showMessage(config, message, isError = false) {
        const element = $(config.message);
        element.textContent = message;
        element.style.color = isError
            ? "var(--danger-color, #b91c1c)"
            : "var(--muted-text, #64748b)";
    }

    function numericValue(id) {
        const raw = $(id).value.trim();
        if (raw === "") return null;
        const value = Number(raw);
        return Number.isFinite(value) && value >= 0 ? value : null;
    }

    function updateTotal(config) {
        const first = numericValue(config.fields[0]);
        const second = numericValue(config.fields[1]);
        const valid = first !== null && second !== null;
        $(config.total).textContent = valid
            ? money.format(first + second)
            : "Enter both amounts";
    }

    function loadForm(config, account) {
        const latest = account?.latest_balance;
        const today = localDate();
        $(config.date).value = today;

        if (
            latest &&
            latest.samiran_balance !== null &&
            latest.samiran_balance !== undefined &&
            latest.sukhada_balance !== null &&
            latest.sukhada_balance !== undefined
        ) {
            $(config.fields[0]).value = latest.samiran_balance;
            $(config.fields[1]).value = latest.sukhada_balance;
            showMessage(config, `Latest saved total: ${money.format(Number(latest.balance))} (${latest.balance_date}).`);
        } else if (latest) {
            $(config.fields[0]).value = "";
            $(config.fields[1]).value = "";
            showMessage(config, `Existing total: ${money.format(Number(latest.balance))} (${latest.balance_date}). Enter both individual amounts to save a split balance.`);
        } else {
            $(config.fields[0]).value = "";
            $(config.fields[1]).value = "";
            showMessage(config, "No saved balance yet.");
        }

        updateTotal(config);
    }

    async function loadBalances() {
        try {
            const data = await request("/api/manage/balance-snapshots");
            for (const config of configs) {
                const account = (data.accounts || []).find(
                    item => Number(item.account_id) === config.accountId
                );
                loadForm(config, account);
            }
        } catch (error) {
            for (const config of configs) {
                showMessage(config, `Could not load saved balances: ${error.message}`, true);
                $(config.date).value = localDate();
                updateTotal(config);
            }
        }
    }

    async function saveBalance(event, config) {
        event.preventDefault();

        const first = numericValue(config.fields[0]);
        const second = numericValue(config.fields[1]);
        if (first === null || second === null) {
            showMessage(config, "Enter valid non-negative amounts in both fields.", true);
            return;
        }

        if (!$(config.date).value) {
            showMessage(config, "Choose a balance date.", true);
            return;
        }

        const button = $(config.button);
        button.disabled = true;
        showMessage(config, "Saving balance...");

        try {
            const result = await request(
                `/api/manage/balance-snapshots/${config.accountId}`,
                {
                    method: "PUT",
                    body: JSON.stringify({
                        balance_date: $(config.date).value,
                        samiran_balance: first,
                        sukhada_balance: second
                    })
                }
            );

            const saved = result.item;
            showMessage(
                config,
                `Saved total ${money.format(Number(saved.balance))} for ${saved.balance_date}.`
            );
            updateTotal(config);
        } catch (error) {
            showMessage(config, `Could not save balance: ${error.message}`, true);
        } finally {
            button.disabled = false;
        }
    }

    for (const config of configs) {
        for (const field of config.fields) {
            $(field).addEventListener("input", () => updateTotal(config));
        }
        $(config.form).addEventListener("submit", event => saveBalance(event, config));
    }

    loadBalances();
})();
