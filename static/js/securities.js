"use strict";

const BROKER_CONFIG = {
    "Zerodha": {
        containerId: "zerodha-securities",
        allowedTypes: ["STOCK", "ETF"],
        currency: "INR",
        country: "India"
    },
    "INDmoney": {
        containerId: "indmoney-securities",
        allowedTypes: ["STOCK", "ETF"],
        currency: "USD",
        country: "USA"
    },
    "Paytm Money": {
        containerId: "paytm-securities",
        allowedTypes: ["MUTUAL_FUND"],
        currency: "INR",
        country: "India"
    }
};

let securitiesCache = [];
let classificationsCache = null;
let accountsCache = null;

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    })[character]);
}

function formatInstrumentType(value) {
    const labels = {
        STOCK: "Stock",
        ETF: "ETF",
        MUTUAL_FUND: "Mutual Fund",
        PRECIOUS_METAL: "Precious Metal"
    };

    return labels[value] || value || "—";
}

function setSecurityMessage(message, isError = false) {
    const element = document.getElementById("security-message");
    element.textContent = message;
    element.classList.toggle("error", isError);
    element.classList.toggle("success", !isError && Boolean(message));
}

function renderSecuritiesTable(securities, accountName) {
    if (!securities.length) {
        return '<p class="securities-empty-state">No securities found for this account.</p>';
    }

    const rows = securities.map(security => {
        const account = (security.accounts || []).find(
            item => item.account_name === accountName
        );

        const isActive = security.is_active === true
            && account?.is_active === true;

        const status = isActive ? "Active" : "Inactive";

        return `
            <tr>
                <td>
                    <strong>${escapeHtml(security.name)}</strong>
                    <div class="security-subtext">
                        ${escapeHtml(security.symbol || "—")}
                    </div>
                </td>
                <td>${escapeHtml(formatInstrumentType(security.instrument_type))}</td>
                <td>${escapeHtml(security.exchange || "—")}</td>
                <td>${escapeHtml(security.currency || "—")}</td>
                <td>${escapeHtml(security.country || "—")}</td>
                <td>${escapeHtml(security.classification_name || "Unclassified")}</td>
                <td>
                    <span class="status-badge ${status.toLowerCase()}">
                        ${status}
                    </span>
                </td>
                <td>
                    <div class="security-actions">
                        <button type="button"
                                class="secondary-button security-edit-button"
                                data-edit-security="${escapeHtml(security.id)}"
                                data-edit-account="${escapeHtml(accountName)}">
                            Edit
                        </button>
                        ${account?.is_active === true ? `
                            <button type="button"
                                    class="secondary-button security-deactivate-button"
                                    data-deactivate-relationship="${escapeHtml(account.account_security_id)}"
                                    data-deactivate-name="${escapeHtml(security.name)}"
                                    data-deactivate-account="${escapeHtml(accountName)}">
                                Deactivate
                            </button>
                        ` : `
                            <button type="button"
                                    class="secondary-button security-activate-button"
                                    data-activate-relationship="${escapeHtml(account.account_security_id)}"
                                    data-activate-name="${escapeHtml(security.name)}"
                                    data-activate-account="${escapeHtml(accountName)}">
                                Activate
                            </button>
                        `}
                    </div>
                </td>
            </tr>
        `;
    }).join("");

    return `
        <div class="table-wrap">
            <table class="securities-table">
                <thead>
                    <tr>
                        <th>Name / Symbol</th>
                        <th>Type</th>
                        <th>Exchange</th>
                        <th>Currency</th>
                        <th>Country</th>
                        <th>Classification</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

async function loadSecurities() {
    const containers = Object.values(BROKER_CONFIG).map(
        config => document.getElementById(config.containerId)
    );

    containers.forEach(container => {
        container.textContent = "Loading securities...";
    });

    try {
        const response = await fetch("/api/manage/securities");
        if (!response.ok) {
            throw new Error("Unable to load securities.");
        }

        securitiesCache = await response.json();

        for (const [accountName, config] of Object.entries(BROKER_CONFIG)) {
            const container = document.getElementById(config.containerId);

            const filtered = securitiesCache.filter(security => {
                const account = (security.accounts || []).find(
                    item => item.account_name === accountName
                );

                return Boolean(account)
                    && config.allowedTypes.includes(security.instrument_type)
                    && security.currency === config.currency
                    && security.country === config.country;
            });

            container.innerHTML = renderSecuritiesTable(filtered, accountName);

            container.querySelectorAll("[data-edit-security]").forEach(button => {
                button.addEventListener("click", () => {
                    openSecurityForm(
                        button.dataset.editAccount,
                        Number(button.dataset.editSecurity)
                    );
                });
            });

            container.querySelectorAll("[data-deactivate-relationship]").forEach(button => {
                button.addEventListener("click", () => {
                    deactivateSecurityRelationship(
                        Number(button.dataset.deactivateRelationship),
                        button.dataset.deactivateName,
                        button.dataset.deactivateAccount
                    );
                });
            });

            container.querySelectorAll("[data-activate-relationship]").forEach(button => {
                button.addEventListener("click", () => {
                    activateSecurityRelationship(
                        Number(button.dataset.activateRelationship),
                        button.dataset.activateName,
                        button.dataset.activateAccount
                    );
                });
            });
        }
    } catch (error) {
        console.error(error);
        containers.forEach(container => {
            container.textContent =
                "Unable to load securities. Please refresh the page.";
        });
    }
}

async function activateSecurityRelationship(
    accountSecurityId,
    securityName,
    accountName
) {
    const confirmed = window.confirm(
        `Reactivate ${securityName} in ${accountName}?`
    );

    if (!confirmed) {
        return;
    }

    setSecurityMessage("");

    try {
        const response = await fetch(
            `/api/manage/security-accounts/${accountSecurityId}/activate`,
            { method: "POST" }
        );

        const result = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(result.error || "Unable to activate this relationship.");
        }

        setSecurityMessage(
            `${securityName} was reactivated in ${accountName}.`
        );
        await loadSecurities();
    } catch (error) {
        console.error(error);
        setSecurityMessage(error.message, true);
    }
}

async function deactivateSecurityRelationship(
    accountSecurityId,
    securityName,
    accountName
) {
    const confirmed = window.confirm(
        `Deactivate ${securityName} in ${accountName}?\\n\\n` +
        "This will preserve its history. It cannot be undone from this action."
    );

    if (!confirmed) {
        return;
    }

    setSecurityMessage("");

    try {
        const response = await fetch(
            `/api/manage/security-accounts/${accountSecurityId}/deactivate`,
            { method: "POST" }
        );

        const result = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(result.error || "Unable to deactivate this relationship.");
        }

        setSecurityMessage(
            result.security_auto_deactivated
                ? `${securityName} was deactivated because it has no remaining active portfolio relationship.`
                : `${securityName} was deactivated in ${accountName}.`
        );

        await loadSecurities();
    } catch (error) {
        console.error(error);
        setSecurityMessage(error.message, true);
    }
}

async function loadFormOptions() {
    if (classificationsCache && accountsCache) {
        return;
    }

    const [classificationResponse, accountResponse] = await Promise.all([
        fetch("/api/manage/classifications"),
        fetch("/api/manage/accounts")
    ]);

    if (!classificationResponse.ok || !accountResponse.ok) {
        throw new Error("Unable to load accounts or classifications.");
    }

    classificationsCache = await classificationResponse.json();
    accountsCache = await accountResponse.json();
}

function getActiveLeafClassifications() {
    const parentIds = new Set(
        classificationsCache
            .filter(item => item.parent_id !== null)
            .map(item => Number(item.parent_id))
    );

    return classificationsCache.filter(item =>
        item.is_active === true && !parentIds.has(Number(item.id))
    );
}

function getBrokerAccount(brokerName) {
    return accountsCache.find(account =>
        account.name === brokerName
        && account.is_active === true
        && account.account_role === "PORTFOLIO"
    );
}

function renderSecurityForm(brokerName, security = null) {
    const config = BROKER_CONFIG[brokerName];
    const account = getBrokerAccount(brokerName);
    const classifications = getActiveLeafClassifications();
    const container = document.getElementById("security-form-container");

    if (!config || !account) {
        throw new Error(
            `An active portfolio account was not found for ${brokerName}.`
        );
    }

    const association = security
        ? (security.accounts || []).find(
            item => item.account_name === brokerName
        )
        : null;

    if (security && !association) {
        throw new Error("The security is not associated with this account.");
    }

    if (!classifications.length) {
        throw new Error("No active leaf classifications are available.");
    }

    const instrumentOptions = config.allowedTypes.map(type => `
        <option value="${escapeHtml(type)}"
            ${security?.instrument_type === type ? "selected" : ""}>
            ${escapeHtml(formatInstrumentType(type))}
        </option>
    `).join("");

    const currentClassificationId = security?.classification_id == null
        ? ""
        : String(security.classification_id);

    const classificationOptions = classifications.map(item => `
        <option value="${escapeHtml(item.id)}"
            ${String(item.id) === currentClassificationId ? "selected" : ""}>
            ${escapeHtml(item.name)}
        </option>
    `).join("");

    const currentClassificationAvailable = classifications.some(
        item => String(item.id) === currentClassificationId
    );

    const classificationNotice = security
        && currentClassificationId
        && !currentClassificationAvailable
        ? '<option value="" selected>Select an active classification</option>'
        : '<option value="">Select classification</option>';

    const fieldValue = value => escapeHtml(value ?? "");
    const openingDate = association?.opened_on
        ? String(association.opened_on).slice(0, 10)
        : "";

    container.innerHTML = `
        <section class="section securities-form-section" id="security-form-section">
            <div class="section-header">
                <h3>${security ? "Edit Security" : "Add Security"} — ${escapeHtml(brokerName)}</h3>
            </div>

            <form id="security-form">
                <div class="form-grid">
                    <label>
                        Security name *
                        <input name="name" type="text" maxlength="200" required
                               value="${fieldValue(security?.name)}">
                    </label>

                    <label>
                        Instrument type *
                        <select name="instrument_type" required>
                            ${instrumentOptions}
                        </select>
                    </label>

                    <label>
                        Symbol
                        <input name="symbol" type="text" maxlength="50"
                               value="${fieldValue(security?.symbol)}">
                    </label>

                    <label>
                        Exchange
                        <input name="exchange" type="text" maxlength="50"
                               value="${fieldValue(security?.exchange)}">
                    </label>

                    <label>
                        Currency
                        <input name="currency" type="text"
                               value="${config.currency}" readonly>
                    </label>

                    <label>
                        Country
                        <input name="country" type="text"
                               value="${config.country}" readonly>
                    </label>

                    <label>
                        Classification *
                        <select name="classification_id" required>
                            ${classificationNotice}
                            ${classificationOptions}
                        </select>
                    </label>

                    <label>
                        Broker symbol
                        <input name="broker_symbol" type="text" maxlength="100"
                               value="${fieldValue(association?.broker_symbol)}">
                    </label>

                    <label>
                        Broker security ID
                        <input name="broker_security_id" type="text" maxlength="100"
                               value="${fieldValue(association?.broker_security_id)}">
                    </label>

                    <label>
                        Opening date
                        <input name="opened_on" type="date"
                               value="${fieldValue(openingDate)}">
                    </label>
                </div>

                <div class="form-actions">
                    <button type="submit" class="primary-button">
                        ${security ? "Save Changes" : "Save Security"}
                    </button>
                    <button type="button" class="secondary-button"
                            id="cancel-security-form">
                        Cancel
                    </button>
                </div>

                <p id="security-form-error" class="security-form-error"
                   role="alert"></p>
            </form>
        </section>
    `;

    container.scrollIntoView({ behavior: "smooth", block: "start" });

    document.getElementById("cancel-security-form").addEventListener(
        "click",
        () => {
            container.innerHTML = "";
            setSecurityMessage("");
        }
    );

    document.getElementById("security-form").addEventListener(
        "submit",
        event => submitSecurityForm(
            event,
            brokerName,
            account.id,
            security
        )
    );
}

async function openSecurityForm(brokerName, securityId = null) {
    setSecurityMessage("");

    try {
        await loadFormOptions();

        const security = securityId === null
            ? null
            : securitiesCache.find(item => Number(item.id) === securityId);

        if (securityId !== null && !security) {
            throw new Error("Security not found. Refresh the page and try again.");
        }

        renderSecurityForm(brokerName, security);
    } catch (error) {
        console.error(error);
        setSecurityMessage(error.message, true);
    }
}

async function submitSecurityForm(event, brokerName, accountId, security = null) {
    event.preventDefault();

    const form = event.currentTarget;
    const submitButton = form.querySelector('button[type="submit"]');
    const errorElement = document.getElementById("security-form-error");
    const formData = new FormData(form);
    const config = BROKER_CONFIG[brokerName];

    const payload = {
        name: String(formData.get("name") || "").trim(),
        instrument_type: formData.get("instrument_type"),
        currency: config.currency,
        country: config.country,
        classification_id: Number(formData.get("classification_id")),
        symbol: String(formData.get("symbol") || "").trim(),
        exchange: String(formData.get("exchange") || "").trim(),
        broker_symbol: String(formData.get("broker_symbol") || "").trim(),
        broker_security_id: String(
            formData.get("broker_security_id") || ""
        ).trim(),
        opened_on: formData.get("opened_on") || null
    };

    if (!security) {
        payload.account_id = Number(accountId);
    } else {
        // The update endpoint requires this Boolean. Preserve the existing status.
        payload.is_active = security.is_active === true;
    }

    if (!payload.name) {
        errorElement.textContent = "Security name is required.";
        return;
    }

    if (!payload.classification_id) {
        errorElement.textContent = "Please select a classification.";
        return;
    }

    if (!config.allowedTypes.includes(payload.instrument_type)) {
        errorElement.textContent =
            "This instrument type is not allowed for the selected broker.";
        return;
    }

    submitButton.disabled = true;
    submitButton.textContent = security ? "Saving Changes..." : "Saving...";
    errorElement.textContent = "";

    try {
        const response = await fetch(
            security
                ? `/api/manage/securities/${security.id}`
                : "/api/manage/securities",
            {
                method: security ? "PUT" : "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            }
        );

        const result = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(
                result.error || (security
                    ? "Unable to update security."
                    : "Unable to save security.")
            );
        }

        document.getElementById("security-form-container").innerHTML = "";
        setSecurityMessage(
            security
                ? `${payload.name} was updated successfully.`
                : `${payload.name} was added successfully.`
        );
        await loadSecurities();
    } catch (error) {
        errorElement.textContent = error.message;
    } finally {
        if (submitButton.isConnected) {
            submitButton.disabled = false;
            submitButton.textContent = security ? "Save Changes" : "Save Security";
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    loadSecurities();

    document.querySelectorAll("[data-account]").forEach(button => {
        button.addEventListener("click", () => {
            openSecurityForm(button.dataset.account);
        });
    });
});