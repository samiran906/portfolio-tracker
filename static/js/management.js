const accountsBody = document.getElementById("management-accounts-body");
const accountFormContainer = document.getElementById("account-form-container");
const accountForm = document.getElementById("account-form");

const accountId = document.getElementById("account-id");
const accountName = document.getElementById("account-name");
const accountType = document.getElementById("account-type");
const accountCurrency = document.getElementById("account-currency");
const accountRole = document.getElementById("account-role");

const accountFormTitle = document.getElementById("account-form-title");
const addAccountButton = document.getElementById("add-account-button");
const cancelAccountButton = document.getElementById("cancel-account-button");

const classificationFormContainer = document.getElementById(
    "classification-form-container"
);

const classificationForm = document.getElementById(
    "classification-form"
);

const classificationFormTitle = document.getElementById(
    "classification-form-title"
);

const classificationId = document.getElementById(
    "classification-id"
);

const classificationName = document.getElementById(
    "classification-name"
);

const classificationParent = document.getElementById(
    "classification-parent"
);

const classificationDescription = document.getElementById(
    "classification-description"
);

const addClassificationButton = document.getElementById(
    "add-classification-button"
);

const cancelClassificationButton = document.getElementById(
    "cancel-classification-button"
);

let classificationsCache = [];


function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function accountTypeLabel(value) {
    const labels = {
        BANK: "Bank",
        BROKER: "Broker",
        RETIREMENT: "Retirement",
        OTHER: "Other"
    };

    return labels[value] || value || "—";
}


function accountRoleLabel(value) {
    return value === "BALANCE_ONLY"
        ? "Balance Only"
        : "Portfolio";
}


function statusLabel(isActive) {
    return isActive ? "Active" : "Inactive";
}


function renderAccounts(accounts) {

    if (!accounts.length) {
        accountsBody.innerHTML = `
            <tr>
                <td colspan="6" class="muted">
                    No accounts found.
                </td>
            </tr>
        `;

        return;
    }


    accountsBody.innerHTML = accounts.map(account => `
        <tr>

            <td>${escapeHtml(account.name)}</td>

            <td>${escapeHtml(accountTypeLabel(account.account_type))}</td>

            <td>${escapeHtml(account.base_currency)}</td>

            <td>${escapeHtml(accountRoleLabel(account.account_role))}</td>

            <td>
                <span class="status-badge ${account.is_active ? "active" : "inactive"}">
                    ${statusLabel(account.is_active)}
                </span>
            </td>

            <td>
                <div class="table-actions">

                    <button
                        type="button"
                        class="secondary-button"
                        data-action="edit"
                        data-id="${account.id}"
                    >
                        Edit
                    </button>

                    <button
                        type="button"
                        class="secondary-button"
                        data-action="toggle"
                        data-id="${account.id}"
                    >
                        ${account.is_active ? "Deactivate" : "Activate"}
                    </button>

                </div>
            </td>

        </tr>
    `).join("");
}


async function loadAccounts() {

    accountsBody.innerHTML = `
        <tr>
            <td colspan="6" class="muted">
                Loading accounts...
            </td>
        </tr>
    `;


    try {

        const response = await fetch("/api/manage/accounts");

        const data = await response.json();


        if (!response.ok) {
            throw new Error(
                data.error || "Unable to load accounts"
            );
        }


        renderAccounts(data);

    } catch (error) {

        accountsBody.innerHTML = `
            <tr>
                <td colspan="6" class="negative">
                    ${escapeHtml(error.message)}
                </td>
            </tr>
        `;

        console.error("Unable to load accounts:", error);
    }
}

async function loadClassifications() {
    const response = await fetch("/api/manage/classifications");

    if (!response.ok) {
        throw new Error("Failed to load classifications.");
    }

    const classifications = await response.json();

    classificationsCache = classifications;

    renderClassifications(classifications);
}

function renderClassifications(classifications) {

    const tbody = document.getElementById(
        "management-classifications-body"
    );

    if (!tbody) {
        return;
    }

    if (!classifications.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="muted">
                    No classifications found.
                </td>
            </tr>
        `;

        return;
    }

    const childrenByParent = new Map();

    classifications.forEach(classification => {

        const parentId = classification.parent_id === null
            ? null
            : Number(classification.parent_id);

        if (!childrenByParent.has(parentId)) {
            childrenByParent.set(parentId, []);
        }

        childrenByParent.get(parentId).push(classification);
    });


    for (const children of childrenByParent.values()) {
        children.sort((a, b) =>
            a.name.localeCompare(b.name)
        );
    }


    const rows = [];


    function addClassification(classification, level) {

        rows.push({
            classification,
            level
        });

        const children = childrenByParent.get(
            Number(classification.id)
        ) || [];

        children.forEach(child => {
            addClassification(child, level + 1);
        });
    }


    const topLevel = childrenByParent.get(null) || [];

    topLevel.forEach(classification => {
        addClassification(classification, 0);
    });


    tbody.innerHTML = rows.map(({ classification, level }) => {

        const indentation = level * 24;

        const statusClass = classification.is_active
            ? "active"
            : "inactive";

        const statusText = classification.is_active
            ? "Active"
            : "Inactive";

        const parentName = classification.parent_id === null
            ? "—"
            : (
                classifications.find(
                    item =>
                        Number(item.id) ===
                        Number(classification.parent_id)
                )?.name || "—"
            );

        return `
            <tr>

                <td>
                    <span
                        class="classification-name"
                        style="padding-left: ${indentation}px;"
                    >
                        ${level > 0 ? "↳ " : ""}
                        ${escapeHtml(classification.name)}
                    </span>
                </td>

                <td>
                    ${escapeHtml(parentName)}
                </td>

                <td>
                    ${escapeHtml(
                        classification.description || "—"
                    )}
                </td>

                <td>
                    <span class="status-badge ${statusClass}">
                        ${statusText}
                    </span>
                </td>

                <td>
                    <div class="table-actions">

                        <button
                            type="button"
                            class="secondary-button"
                            data-action="edit-classification"
                            data-id="${classification.id}"
                        >
                            Edit
                        </button>

                        <button
                            type="button"
                            class="secondary-button"
                            data-action="toggle-classification"
                            data-id="${classification.id}"
                        >
                            ${classification.is_active
                                ? "Deactivate"
                                : "Activate"}
                        </button>

                    </div>
                </td>

            </tr>
        `;
    }).join("");
}

function openAddClassificationForm() {

    classificationForm.reset();

    classificationId.value = "";

    classificationFormTitle.textContent = "Add Classification";

    populateClassificationParentOptions();

    classificationFormContainer.classList.remove("hidden");

    classificationName.focus();
}


function closeClassificationForm() {

    classificationForm.reset();

    classificationId.value = "";

    classificationFormContainer.classList.add("hidden");
}

function populateClassificationParentOptions(excludeId = null) {

    const currentClassificationId = excludeId
        ? Number(excludeId)
        : null;

    classificationParent.innerHTML = `
        <option value="">None — Top Level</option>
    `;

    classificationsCache
        .filter(classification =>
            classification.is_active &&
            Number(classification.id) !== currentClassificationId
        )
        .sort((a, b) =>
            a.name.localeCompare(b.name)
        )
        .forEach(classification => {

            const option = document.createElement("option");

            option.value = classification.id;
            option.textContent = classification.name;

            classificationParent.appendChild(option);
        });
}

function openEditClassificationForm(classification) {

    classificationForm.reset();

    classificationId.value = classification.id;

    classificationFormTitle.textContent = "Edit Classification";

    classificationName.value = classification.name;

    classificationDescription.value =
        classification.description || "";

    populateClassificationParentOptions(
        classification.id
    );

    classificationParent.value =
        classification.parent_id === null
            ? ""
            : String(classification.parent_id);

    classificationFormContainer.classList.remove("hidden");

    classificationName.focus();
}

async function handleClassificationAction(event) {

    const button = event.target.closest("button[data-action]");

    if (!button) {
        return;
    }

    const action = button.dataset.action;
    const id = Number(button.dataset.id);

    const classification = classificationsCache.find(
        item => item.id === id
    );

    if (!classification) {
        return;
    }


    if (action === "edit-classification") {

        openEditClassificationForm(classification);

        return;
    }


    if (action === "toggle-classification") {

        const newStatus = !classification.is_active;

        const actionText = newStatus
            ? "activate"
            : "deactivate";

        const confirmed = confirm(
            `Are you sure you want to ${actionText} "${classification.name}"?`
        );

        if (!confirmed) {
            return;
        }


        const payload = {
            name: classification.name,
            parent_id: classification.parent_id,
            description: classification.description || "",
            is_active: newStatus
        };


        try {

            const response = await fetch(
                `/api/manage/classifications/${classification.id}`,
                {
                    method: "PUT",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify(payload)
                }
            );


            const data = await response.json();


            if (!response.ok) {
                throw new Error(
                    data.error ||
                    `Unable to ${actionText} classification.`
                );
            }


            await loadClassifications();

        } catch (error) {

            alert(error.message);

            console.error(
                `Unable to ${actionText} classification:`,
                error
            );
        }

    }
}

async function saveClassification(event) {

    event.preventDefault();

    const name = classificationName.value.trim();

    if (!name) {
        alert("Classification name is required.");
        classificationName.focus();
        return;
    }


    const id = classificationId.value;

    const existingClassification = id
        ? classificationsCache.find(
            classification => classification.id === Number(id)
        )
        : null;

    const payload = {
        name: name,
        parent_id: classificationParent.value
            ? Number(classificationParent.value)
            : null,
        description: classificationDescription.value.trim()
    };

    if (existingClassification) {
        payload.is_active = existingClassification.is_active;
    }


    try {

        const url = id
            ? `/api/manage/classifications/${id}`
            : "/api/manage/classifications";

        const method = id
            ? "PUT"
            : "POST";


        const response = await fetch(
            url,
            {
                method: method,
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            }
        );


        const data = await response.json();


        if (!response.ok) {
            throw new Error(
                data.error ||
                (
                    id
                        ? "Unable to update classification."
                        : "Unable to create classification."
                )
            );
        }


        closeClassificationForm();

        await loadClassifications();

    } catch (error) {

        alert(error.message);

        console.error(
            "Unable to save classification:",
            error
        );
    }
}

function openAddAccountForm() {

    accountForm.reset();

    accountId.value = "";
    accountCurrency.value = "INR";
    accountRole.value = "PORTFOLIO";

    accountFormTitle.textContent = "Add Account";

    accountFormContainer.classList.remove("hidden");

    accountName.focus();
}


function openEditAccountForm(account) {

    accountId.value = account.id;
    accountName.value = account.name;
    accountType.value = account.account_type;
    accountCurrency.value = account.base_currency;
    accountRole.value = account.account_role;

    accountFormTitle.textContent = "Edit Account";

    accountFormContainer.classList.remove("hidden");

    accountName.focus();
}


function closeAccountForm() {

    accountForm.reset();

    accountId.value = "";

    accountCurrency.value = "INR";
    accountRole.value = "PORTFOLIO";

    accountFormContainer.classList.add("hidden");
}


async function saveAccount(event) {

    event.preventDefault();


    const id = accountId.value;


    const payload = {
        name: accountName.value.trim(),
        account_type: accountType.value,
        base_currency: accountCurrency.value.trim().toUpperCase(),
        account_role: accountRole.value
    };


    if (!payload.name) {
        alert("Account name is required.");
        accountName.focus();
        return;
    }


    if (!payload.account_type) {
        alert("Account type is required.");
        accountType.focus();
        return;
    }


    if (payload.base_currency.length !== 3) {
        alert("Currency must be a 3-letter currency code.");
        accountCurrency.focus();
        return;
    }


    if (!payload.account_role) {
        alert("Portfolio role is required.");
        accountRole.focus();
        return;
    }


    try {

        const url = id
            ? `/api/manage/accounts/${id}`
            : "/api/manage/accounts";


        const method = id ? "PUT" : "POST";


        if (id) {
            const accounts = await fetch("/api/manage/accounts")
            .then(response => response.json());

            const existingAccount = accounts.find(
                account => Number(account.id) === Number(id)
            );

            if (!existingAccount) {
                throw new Error("Account could not be found.");
            }

            payload.is_active = existingAccount.is_active;
        }


        const response = await fetch(url, {
            method,
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });


        const data = await response.json();


        if (!response.ok) {
            throw new Error(
                data.error || "Unable to save account"
            );
        }


        closeAccountForm();

        await loadAccounts();

    } catch (error) {

        alert(error.message);

        console.error("Unable to save account:", error);
    }
}


async function toggleAccount(account) {

    const action = account.is_active
        ? "deactivate"
        : "activate";


    const confirmed = confirm(
        `Are you sure you want to ${action} "${account.name}"?`
    );


    if (!confirmed) {
        return;
    }


    try {

        const response = await fetch(
            `/api/manage/accounts/${account.id}`,
            {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    name: account.name,
                    account_type: account.account_type,
                    base_currency: account.base_currency,
                    account_role: account.account_role,
                    is_active: !account.is_active
                })
            }
        );


        const data = await response.json();


        if (!response.ok) {
            throw new Error(
                data.error || `Unable to ${action} account`
            );
        }


        await loadAccounts();

    } catch (error) {

        alert(error.message);

        console.error(
            `Unable to ${action} account:`,
            error
        );
    }
}


async function handleAccountAction(event) {

    const button = event.target.closest("button[data-action]");


    if (!button) {
        return;
    }


    const id = Number(button.dataset.id);


    try {

        const response = await fetch("/api/manage/accounts");

        const accounts = await response.json();


        if (!response.ok) {
            throw new Error(
                accounts.error || "Unable to load accounts"
            );
        }


        const account = accounts.find(
            item => Number(item.id) === id
        );


        if (!account) {
            throw new Error("Account could not be found.");
        }


        if (button.dataset.action === "edit") {
            openEditAccountForm(account);
        }


        if (button.dataset.action === "toggle") {
            await toggleAccount(account);
        }

    } catch (error) {

        alert(error.message);

        console.error(
            "Unable to perform account action:",
            error
        );
    }
}

addClassificationButton.addEventListener(
    "click",
    openAddClassificationForm
);


cancelClassificationButton.addEventListener(
    "click",
    closeClassificationForm
);


classificationForm.addEventListener(
    "submit",
    saveClassification
);

addAccountButton.addEventListener(
    "click",
    openAddAccountForm
);


cancelAccountButton.addEventListener(
    "click",
    closeAccountForm
);


accountForm.addEventListener(
    "submit",
    saveAccount
);


accountsBody.addEventListener(
    "click",
    handleAccountAction
);


document.addEventListener(
    "DOMContentLoaded",
    async () => {
        try {
            await Promise.all([
                loadAccounts(),
                loadClassifications()
            ]);
        } catch (error) {
            console.error("Unable to initialize management page:", error);
        }
    }
);

document
    .getElementById("management-classifications-body")
    .addEventListener(
        "click",
        handleClassificationAction
    );