(() => {
    "use strict";

    const API = {
        accounts: "/api/manage/accounts",
        securities: "/api/manage/securities",
        transactions: "/api/manage/security-transactions"
    };

    const PAGE_SIZE = 25;

    const elements = {
        filters: document.getElementById("transaction-filters"),
        account: document.getElementById("filter-account"),
        security: document.getElementById("filter-security"),
        type: document.getElementById("filter-type"),
        reset: document.getElementById("reset-transaction-filters"),
        count: document.getElementById("transaction-count"),
        pageSummary: document.getElementById("transaction-page-summary"),
        message: document.getElementById("transaction-message"),
        body: document.getElementById("transactions-table-body"),
        previous: document.getElementById("transaction-previous"),
        next: document.getElementById("transaction-next"),
        pageLabel: document.getElementById("transaction-page-label"),
        toggleEntryForm: document.getElementById("toggle-transaction-form"),
        entryTitle: document.getElementById("transaction-entry-title"),
        entryForm: document.getElementById("transaction-entry-form"),
        entryAccount: document.getElementById("entry-account"),
        entrySecuritySearch: document.getElementById("entry-security-search"),
        entrySecurity: document.getElementById("entry-security"),
        entrySecurityPicker: document.getElementById("entry-security-picker"),
        entrySecurityOptions: document.getElementById("entry-security-options"),
        entryDate: document.getElementById("entry-date"),
        entryType: document.getElementById("entry-type"),
        tradeFields: document.getElementById("entry-trade-fields"),
        corporateFields: document.getElementById("entry-corporate-fields"),
        entryQuantity: document.getElementById("entry-quantity"),
        entryPrice: document.getElementById("entry-price"),
        entrySettlement: document.getElementById("entry-settlement"),
        entryActionFrom: document.getElementById("entry-action-from"),
        entryActionTo: document.getElementById("entry-action-to"),
        entryReference: document.getElementById("entry-reference"),
        entryNotes: document.getElementById("entry-notes"),
        entryMessage: document.getElementById("transaction-entry-message"),
        saveEntry: document.getElementById("save-transaction"),
        cancelEntry: document.getElementById("cancel-transaction-form")
    };

    const state = {
        page: 1,
        totalPages: 1,
        accounts: [],
        securities: [],
        entryRelationships: [],
        currentTransactions: new Map(),
        editingTransactionId: null,
        loading: false
    };

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, character => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[character]);
    }

    function formatNumber(value, maximumFractionDigits = 2) {
        if (value === null || value === undefined || value === "") {
            return "—";
        }

        const number = Number(value);

        if (!Number.isFinite(number)) {
            return "—";
        }

        return new Intl.NumberFormat("en-IN", {
            minimumFractionDigits: 0,
            maximumFractionDigits
        }).format(number);
    }

    function formatMoney(value, currency) {
        if (value === null || value === undefined || value === "") {
            return "—";
        }

        const number = Number(value);

        if (!Number.isFinite(number)) {
            return "—";
        }

        try {
            return new Intl.NumberFormat("en-IN", {
                style: "currency",
                currency: currency || "INR",
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            }).format(number);
        } catch {
            return `${escapeHtml(currency || "")} ${formatNumber(value, 2)}`;
        }
    }

    function formatDate(value) {
        if (!value) {
            return "—";
        }

        // Parse the date as a local calendar date to avoid timezone shifts.
        const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);

        if (!match) {
            return escapeHtml(value);
        }

        return `${match[3]}-${match[2]}-${match[1]}`;
    }

    async function fetchJson(url) {
        const response = await fetch(url, {
            headers: { Accept: "application/json" }
        });

        const contentType = response.headers.get("content-type") || "";

        if (!contentType.includes("application/json")) {
            throw new Error(`Unexpected response from server (HTTP ${response.status}).`);
        }

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || `Request failed (HTTP ${response.status}).`);
        }

        return data;
    }

    function addOption(select, value, label) {
        const option = document.createElement("option");
        option.value = String(value);
        option.textContent = label;
        select.appendChild(option);
    }

    async function loadFilters() {
        const [accounts, securities] = await Promise.all([
            fetchJson(API.accounts),
            fetchJson(API.securities)
        ]);

        state.accounts = accounts;
        state.securities = securities;

        // Only accounts that have a security transaction relationship are useful
        // here. The transaction API remains the source of truth for the history.
        const accountIds = new Set(
            securities.flatMap(security =>
                (security.accounts || []).map(account => Number(account.account_id))
            )
        );

        accounts
            .filter(account => accountIds.has(Number(account.id)))
            .sort((a, b) => a.name.localeCompare(b.name))
            .forEach(account => {
                const inactiveLabel = account.is_active ? "" : " (inactive)";
                addOption(
                    elements.account,
                    account.id,
                    `${account.name}${inactiveLabel}`
                );
            });

        securities
            .slice()
            .sort((a, b) => {
                const nameOrder = a.name.localeCompare(b.name);
                return nameOrder || String(a.symbol).localeCompare(String(b.symbol));
            })
            .forEach(security => {
                const inactiveLabel = security.is_active ? "" : " (inactive)";
                const label = `${security.name} (${security.symbol})${inactiveLabel}`;
                addOption(elements.security, security.id, label);
            });
    }

    function getFilters() {
        const params = new URLSearchParams({
            page: String(state.page),
            page_size: String(PAGE_SIZE)
        });

        if (elements.account.value) {
            params.set("account_id", elements.account.value);
        }

        if (elements.security.value) {
            params.set("security_id", elements.security.value);
        }

        if (elements.type.value) {
            params.set("transaction_type", elements.type.value);
        }

        return params;
    }

    function renderTransaction(row) {
        const type = String(row.transaction_type || "").toUpperCase();
        const isCorporateAction = type === "BONUS" || type === "SPLIT";

        let quantityOrRatio = formatNumber(row.quantity, 6);

        if (isCorporateAction) {
            const from = row.corporate_action_from;
            const to = row.corporate_action_to;

            quantityOrRatio = from != null && to != null
                ? `${formatNumber(from, 6)} : ${formatNumber(to, 6)}`
                : "Ratio not recorded";
        }

        const price = isCorporateAction
            ? "—"
            : formatMoney(row.price, row.currency);

        const settlement = isCorporateAction
            ? "—"
            : formatMoney(row.settlement_amount, row.currency);

        return `
            <tr>
                <td>${escapeHtml(formatDate(row.transaction_date))}</td>
                <td>${escapeHtml(row.account_name)}</td>
                <td>
                    <span>${escapeHtml(row.security_name)}</span>
                    <small class="transaction-symbol">${escapeHtml(row.symbol)}</small>
                </td>
                <td><span class="transaction-type">${escapeHtml(type)}</span></td>
                <td class="numeric-cell">${escapeHtml(quantityOrRatio)}</td>
                <td class="numeric-cell">${escapeHtml(price)}</td>
                <td class="numeric-cell">${escapeHtml(settlement)}</td>
                <td class="numeric-cell">${escapeHtml(formatNumber(row.quantity_held, 6))}</td>
                <td class="numeric-cell">${escapeHtml(formatMoney(row.average_cost, row.currency))}</td>
                <td class="transaction-row-actions">
                    <button type="button" class="secondary-button"
                            data-action="edit" data-transaction-id="${Number(row.transaction_id)}">Edit</button>
                    <button type="button" class="secondary-button"
                            data-action="delete" data-transaction-id="${Number(row.transaction_id)}">Delete</button>
                </td>
            </tr>
        `;
    }

    function renderRows(rows) {
        state.currentTransactions = new Map(
            rows.map(row => [Number(row.transaction_id), row])
        );

        if (!rows.length) {
            elements.body.innerHTML = `
                <tr><td colspan="10">No transactions match the selected filters.</td></tr>
            `;
            return;
        }

        elements.body.innerHTML = rows.map(renderTransaction).join("");
    }

    function updatePagination(data) {
        state.page = data.page || 1;
        state.totalPages = Math.max(1, data.total_pages || 1);

        elements.count.textContent = formatNumber(data.total ?? 0, 0);
        elements.pageSummary.textContent = `${state.page} of ${state.totalPages}`;
        elements.pageLabel.textContent =
            `Page ${state.page} of ${state.totalPages}`;

        elements.previous.disabled = state.loading || state.page <= 1;
        elements.next.disabled =
            state.loading || state.page >= state.totalPages;
    }

    async function loadTransactions() {
        if (state.loading) {
            return;
        }

        state.loading = true;
        elements.message.textContent = "Loading transactions...";
        elements.previous.disabled = true;
        elements.next.disabled = true;

        try {
            const params = getFilters();
            const data = await fetchJson(`${API.transactions}?${params.toString()}`);

            renderRows(data.items || []);
            updatePagination(data);
            elements.message.textContent = data.total
                ? `Showing ${data.items.length} transaction(s) on this page.`
                : "No matching transactions.";
        } catch (error) {
            elements.body.innerHTML = `
                <tr><td colspan="10">Unable to load transactions.</td></tr>
            `;
            elements.message.textContent =
                error.message || "Unable to load transactions.";
            elements.count.textContent = "—";
            elements.pageSummary.textContent = "—";
            elements.pageLabel.textContent = "Page unavailable";
        } finally {
            state.loading = false;
            elements.previous.disabled = state.page <= 1;
            elements.next.disabled = state.page >= state.totalPages;
        }
    }

    elements.filters.addEventListener("submit", event => {
        event.preventDefault();
        state.page = 1;
        loadTransactions();
    });

    elements.reset.addEventListener("click", () => {
        elements.filters.reset();
        state.page = 1;
        loadTransactions();
    });

    elements.previous.addEventListener("click", () => {
        if (state.page > 1 && !state.loading) {
            state.page -= 1;
            loadTransactions();
        }
    });

    elements.next.addEventListener("click", () => {
        if (state.page < state.totalPages && !state.loading) {
            state.page += 1;
            loadTransactions();
        }
    });


    function populateEntryRelationships() {
        const accountsById = new Map(
            state.accounts.map(account => [Number(account.id), account])
        );

        state.entryRelationships = [];

        state.securities.forEach(security => {
            if (!security.is_active) {
                return;
            }

            (security.accounts || []).forEach(relationship => {
                const account = accountsById.get(Number(relationship.account_id));

                if (
                    !account ||
                    !account.is_active ||
                    account.account_role !== "PORTFOLIO" ||
                    !relationship.is_active
                ) {
                    return;
                }

                state.entryRelationships.push({
                    accountId: Number(account.id),
                    accountName: account.name,
                    relationshipId: Number(relationship.account_security_id),
                    securityId: Number(security.id),
                    securityName: security.name,
                    symbol: security.symbol
                });
            });
        });

        const eligibleAccountIds = new Set(
            state.entryRelationships.map(item => item.accountId)
        );

        elements.entryAccount.replaceChildren(
            new Option("Choose an account", "")
        );

        state.accounts
            .filter(account => eligibleAccountIds.has(Number(account.id)))
            .sort((a, b) => a.name.localeCompare(b.name))
            .forEach(account => {
                addOption(elements.entryAccount, account.id, account.name);
            });

        renderEntrySecurityOptions();
    }

    function closeEntrySecurityOptions() {
        elements.entrySecurityOptions.hidden = true;
        elements.entrySecuritySearch.setAttribute("aria-expanded", "false");
    }

    function renderEntrySecurityOptions() {
        const accountId = Number(elements.entryAccount.value);
        const query = elements.entrySecuritySearch.value.trim().toLocaleLowerCase();

        elements.entrySecurityOptions.replaceChildren();
        elements.entrySecurity.value = "";

        if (!accountId) {
            elements.entrySecuritySearch.placeholder = "Choose an account first";
            closeEntrySecurityOptions();
            return;
        }

        elements.entrySecuritySearch.placeholder = "Search name or symbol...";
        const matches = state.entryRelationships
            .filter(item => item.accountId === accountId)
            .filter(item =>
                !query ||
                item.securityName.toLocaleLowerCase().includes(query) ||
                String(item.symbol || "").toLocaleLowerCase().includes(query)
            )
            .sort((a, b) =>
                a.securityName.localeCompare(b.securityName) ||
                String(a.symbol || "").localeCompare(String(b.symbol || ""))
            );

        if (!matches.length) {
            const empty = document.createElement("div");
            empty.className = "security-picker-empty";
            empty.textContent = "No matching securities";
            elements.entrySecurityOptions.append(empty);
        } else {
            matches.forEach(item => {
                const option = document.createElement("button");
                option.type = "button";
                option.className = "security-picker-option";
                option.setAttribute("role", "option");
                option.dataset.relationshipId = String(item.relationshipId);
                option.textContent = `${item.securityName} (${item.symbol || "No symbol"})`;
                option.addEventListener("click", () => {
                    elements.entrySecurity.value = String(item.relationshipId);
                    elements.entrySecuritySearch.value = option.textContent;
                    elements.entrySecuritySearch.setCustomValidity("");
                    closeEntrySecurityOptions();
                });
                elements.entrySecurityOptions.append(option);
            });
        }

        elements.entrySecurityOptions.hidden = false;
        elements.entrySecuritySearch.setAttribute("aria-expanded", "true");
    }

    function setEntryTypeFields() {
        const isCorporateAction =
            ["BONUS", "SPLIT"].includes(elements.entryType.value);

        elements.tradeFields.hidden = isCorporateAction;
        elements.corporateFields.hidden = !isCorporateAction;

        elements.entryQuantity.required = !isCorporateAction;
        elements.entryPrice.required = !isCorporateAction;
        elements.entryActionFrom.required = isCorporateAction;
        elements.entryActionTo.required = isCorporateAction;

        elements.entryQuantity.disabled = isCorporateAction;
        elements.entryPrice.disabled = isCorporateAction;
        elements.entrySettlement.disabled = isCorporateAction;
        elements.entryActionFrom.disabled = !isCorporateAction;
        elements.entryActionTo.disabled = !isCorporateAction;
    }

    function setLocalToday() {
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, "0");
        const day = String(now.getDate()).padStart(2, "0");
        elements.entryDate.value = `${year}-${month}-${day}`;
    }

    function resetEntryForm() {
        state.editingTransactionId = null;
        elements.entryTitle.textContent = "Add Security Transaction";
        elements.toggleEntryForm.textContent =
            elements.entryForm.hidden ? "Add transaction" : "Close form";
        elements.entryAccount.disabled = false;
        elements.entrySecuritySearch.disabled = false;
        elements.entryForm.reset();
        elements.entrySecurity.value = "";
        elements.entrySecuritySearch.value = "";
        elements.entrySecuritySearch.disabled = !elements.entryAccount.value;
        elements.entrySecuritySearch.setCustomValidity("");
        closeEntrySecurityOptions();
        setLocalToday();
        elements.entryType.value = "BUY";
        setEntryTypeFields();
        elements.entryMessage.textContent = "";
        elements.saveEntry.disabled = false;
        elements.saveEntry.textContent = "Save transaction";
    }

    function beginEditTransaction(row) {
        resetEntryForm();
        state.editingTransactionId = Number(row.transaction_id);

        const accountId = String(row.account_id);
        let accountOption = Array.from(elements.entryAccount.options)
            .find(option => option.value === accountId);

        if (!accountOption) {
            accountOption = new Option(
                `${row.account_name} (historical)`,
                accountId
            );
            elements.entryAccount.add(accountOption);
        }

        elements.entryAccount.value = accountId;
        elements.entryAccount.disabled = true;

        elements.entrySecurity.value = String(row.account_security_id);
        elements.entrySecuritySearch.value =
            `${row.security_name} (${row.symbol || "No symbol"})`;
        elements.entrySecuritySearch.disabled = true;
        elements.entrySecuritySearch.setCustomValidity("");
        closeEntrySecurityOptions();

        elements.entryDate.value = row.transaction_date || "";
        elements.entryType.value = row.transaction_type;
        elements.entryQuantity.value = row.quantity ?? "";
        elements.entryPrice.value = row.price ?? "";
        elements.entrySettlement.value = row.settlement_amount ?? "";
        elements.entryActionFrom.value = row.corporate_action_from ?? "";
        elements.entryActionTo.value = row.corporate_action_to ?? "";
        elements.entryReference.value = row.reference ?? "";
        elements.entryNotes.value = row.notes ?? "";

        setEntryTypeFields();
        elements.entryTitle.textContent = "Edit Security Transaction";
        elements.saveEntry.textContent = "Update transaction";
        elements.entryMessage.textContent =
            "Editing a saved transaction. Account and security cannot be changed.";
        elements.entryForm.hidden = false;
        elements.toggleEntryForm.textContent = "Cancel editing";
        elements.entryDate.focus();
    }

    async function deleteTransaction(row) {
        const type = String(row.transaction_type || "").toUpperCase();
        const details = ["BONUS", "SPLIT"].includes(type)
            ? `ratio ${row.corporate_action_from ?? "?"}:${row.corporate_action_to ?? "?"}`
            : `quantity ${row.quantity ?? "?"}`;

        const confirmed = window.confirm(
            `Delete this security transaction?\n\n` +
            `Security: ${row.security_name} (${row.symbol || "No symbol"})\n` +
            `Type: ${type}\n` +
            `Date: ${row.transaction_date}\n` +
            `${details}\n\n` +
            `This may be rejected if it would make a later holding negative.`
        );

        if (!confirmed) return;

        elements.message.textContent = "Deleting transaction...";

        try {
            const response = await fetch(
                `${API.transactions}/${Number(row.transaction_id)}`,
                {
                    method: "DELETE",
                    headers: { Accept: "application/json" }
                }
            );

            const contentType = response.headers.get("content-type") || "";
            if (!contentType.includes("application/json")) {
                throw new Error(
                    `Unexpected response from server (HTTP ${response.status}).`
                );
            }

            const result = await response.json();
            if (!response.ok) {
                let message = result.error ||
                    `Unable to delete transaction (HTTP ${response.status}).`;

                if (result.conflicting_transaction_date) {
                    message += ` Conflicting history starts on ${
                        result.conflicting_transaction_date
                    } (${result.conflicting_transaction_type || "transaction"}).`;
                }
                throw new Error(message);
            }

            state.page = 1;
            await loadTransactions();
            elements.message.textContent = "Transaction deleted successfully.";
        } catch (error) {
            elements.message.textContent =
                error.message || "Unable to delete transaction.";
        }
    }

    elements.body.addEventListener("click", event => {
        const button = event.target.closest("button[data-action]");
        if (!button) return;

        const id = Number(button.dataset.transactionId);
        const row = state.currentTransactions.get(id);
        if (!row) {
            elements.message.textContent =
                "That transaction is no longer on this page. Refresh the history and try again.";
            return;
        }

        if (button.dataset.action === "edit") {
            beginEditTransaction(row);
        } else if (button.dataset.action === "delete") {
            deleteTransaction(row);
        }
    });

    async function submitEntryForm(event) {
        event.preventDefault();

        if (!elements.entrySecurity.value) {
            elements.entrySecuritySearch.setCustomValidity(
                "Choose a security from the suggestions."
            );
            elements.entrySecuritySearch.reportValidity();
            elements.entrySecuritySearch.focus();
            return;
        }

        elements.entrySecuritySearch.setCustomValidity("");

        if (!elements.entryForm.reportValidity()) {
            return;
        }

        const transactionType = elements.entryType.value;
        const editingTransactionId = state.editingTransactionId;
        const isEditing = editingTransactionId !== null;
        const payload = {
            transaction_date: elements.entryDate.value,
            transaction_type: transactionType,
            reference: elements.entryReference.value.trim() || null,
            notes: elements.entryNotes.value.trim() || null
        };

        // New transactions must identify the account-security relationship.
        // For edits, the backend updates the existing relationship in place.
        if (!isEditing) {
            payload.account_security_id = Number(elements.entrySecurity.value);
        }

        if (["BUY", "SELL"].includes(transactionType)) {
            payload.quantity = elements.entryQuantity.value;
            payload.price = elements.entryPrice.value;

            if (elements.entrySettlement.value.trim() !== "") {
                payload.settlement_amount = elements.entrySettlement.value;
            }
        } else {
            payload.corporate_action_from = elements.entryActionFrom.value;
            payload.corporate_action_to = elements.entryActionTo.value;
        }

        elements.saveEntry.disabled = true;
        elements.saveEntry.textContent = "Saving...";
        elements.entryMessage.textContent = "Saving transaction...";

        try {
            const url = isEditing
                ? `${API.transactions}/${editingTransactionId}`
                : API.transactions;
            const response = await fetch(url, {
                method: isEditing ? "PUT" : "POST",
                headers: {
                    "Content-Type": "application/json",
                    Accept: "application/json"
                },
                body: JSON.stringify(payload)
            });

            const contentType = response.headers.get("content-type") || "";
            if (!contentType.includes("application/json")) {
                throw new Error(
                    `Unexpected response from server (HTTP ${response.status}).`
                );
            }

            const result = await response.json();

            if (!response.ok) {
                let message = result.error ||
                    `Unable to save transaction (HTTP ${response.status}).`;

                if (result.conflicting_transaction_date) {
                    message += ` Conflicting history starts on ${
                        result.conflicting_transaction_date
                    } (${result.conflicting_transaction_type || "transaction"}).`;
                }

                throw new Error(message);
            }

            // Keep the relevant history filters after adding or editing.
            const selectedRelationship =
                Number(elements.entrySecurity.value);
            const selectedSecurity = state.securities.find(security =>
                (security.accounts || []).some(relationship =>
                    Number(relationship.account_security_id) === selectedRelationship
                )
            );
            const selectedRelationshipData = selectedSecurity?.accounts?.find(
                relationship =>
                    Number(relationship.account_security_id) === selectedRelationship
            );

            if (selectedRelationshipData) {
                elements.account.value = String(selectedRelationshipData.account_id);
            }
            if (selectedSecurity) {
                elements.security.value = String(selectedSecurity.id);
            }

            elements.type.value = transactionType;
            state.page = 1;
            resetEntryForm();
            elements.entryForm.hidden = true;
            elements.toggleEntryForm.textContent = "Add transaction";
            await loadTransactions();

            elements.message.textContent = isEditing
                ? `Transaction ${editingTransactionId} updated successfully.`
                : `Transaction saved successfully (ID ${result.transaction_id}).`;
        } catch (error) {
            elements.entryMessage.textContent =
                error.message || "Unable to save transaction.";
        } finally {
            elements.saveEntry.disabled = false;
            elements.saveEntry.textContent =
                state.editingTransactionId === null
                    ? "Save transaction"
                    : "Update transaction";
        }
    }

    elements.toggleEntryForm.addEventListener("click", () => {
        if (state.editingTransactionId !== null) {
            resetEntryForm();
            elements.entryForm.hidden = true;
            elements.toggleEntryForm.textContent = "Add transaction";
            return;
        }

        elements.entryForm.hidden = !elements.entryForm.hidden;
        elements.toggleEntryForm.textContent =
            elements.entryForm.hidden ? "Add transaction" : "Close form";

        if (!elements.entryForm.hidden) {
            setLocalToday();
            setEntryTypeFields();
        }
    });

    elements.cancelEntry.addEventListener("click", () => {
        resetEntryForm();
        elements.entryForm.hidden = true;
        elements.toggleEntryForm.textContent = "Add transaction";
    });

    elements.entryAccount.addEventListener("change", () => {
        elements.entrySecuritySearch.value = "";
        elements.entrySecurity.value = "";
        elements.entrySecuritySearch.disabled = !elements.entryAccount.value;
        elements.entrySecuritySearch.setCustomValidity("");
        renderEntrySecurityOptions();
    });

    elements.entrySecuritySearch.addEventListener("focus", renderEntrySecurityOptions);
    elements.entrySecuritySearch.addEventListener("input", () => {
        elements.entrySecurity.value = "";
        elements.entrySecuritySearch.setCustomValidity("");
        renderEntrySecurityOptions();
    });

    elements.entrySecuritySearch.addEventListener("keydown", event => {
        if (event.key === "Escape") {
            closeEntrySecurityOptions();
        } else if (event.key === "Enter" && !elements.entrySecurity.value) {
            event.preventDefault();
            const firstOption = elements.entrySecurityOptions.querySelector("button");
            if (firstOption) firstOption.click();
        }
    });

    document.addEventListener("click", event => {
        if (!elements.entrySecurityPicker.contains(event.target)) {
            closeEntrySecurityOptions();
        }
    });

    elements.entryType.addEventListener("change", setEntryTypeFields);
    elements.entryForm.addEventListener("submit", submitEntryForm);

    async function initialize() {
        try {
            await loadFilters();
            populateEntryRelationships();
            resetEntryForm();
            await loadTransactions();
        } catch (error) {
            elements.message.textContent =
                error.message || "Unable to initialize the Transactions page.";
            elements.body.innerHTML = `
                <tr><td colspan="10">Unable to load the required account and security lists.</td></tr>
            `;
        }
    }

    initialize();
})();
