(() => {
    "use strict";

    const PAGE_SIZE = 25;
    const API = {
        accounts: "/api/manage/accounts",
        transactions: "/api/manage/account-transactions",
        walletCash: "/api/manage/wallet-cash"
    };

    const $ = (id) => document.getElementById(id);

    let accounts = [];
    let currentPage = 1;
    let totalPages = 1;
    let editingId = null;
    let loadingTransactions = false;

    const form = $("account-transaction-form");
    const tableBody = $("account-transactions-table-body");

    if (!form || !tableBody || !$("wallet-cash-form")) {
        console.error("Account Transactions: required HTML elements were not found.");
        return;
    }

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (char) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[char]);
    }

    function formatAmount(value, currency = "INR") {
        const amount = Number(value);
        if (!Number.isFinite(amount)) return "—";

        return new Intl.NumberFormat("en-IN", {
            style: "currency",
            currency: currency || "INR",
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(amount);
    }

    function todayLocal() {
        const now = new Date();
        const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
        return local.toISOString().slice(0, 10);
    }

    async function request(url, options = {}) {
        const response = await fetch(url, {
            ...options,
            headers: {
                ...(options.body ? { "Content-Type": "application/json" } : {}),
                ...(options.headers || {})
            }
        });

        const text = await response.text();
        let data = {};

        if (text) {
            try {
                data = JSON.parse(text);
            } catch {
                throw new Error(`Unexpected server response (${response.status}).`);
            }
        }

        if (!response.ok) {
            throw new Error(data.error || data.message || `Request failed (${response.status}).`);
        }

        return data;
    }

    function showMessage(id, message, isError = false) {
        const element = $(id);
        if (!element) return;

        element.textContent = message;
        element.style.color = isError ? "var(--danger-color, #b42318)" : "";
    }

    function portfolioAccounts() {
        return accounts.filter((account) =>
            account.account_role === "PORTFOLIO" &&
            (account.is_active === true || account.is_active === 1)
        );
    }

    function fillAccountSelect(select, placeholder) {
        select.replaceChildren();

        const first = document.createElement("option");
        first.value = "";
        first.textContent = placeholder;
        select.appendChild(first);

        for (const account of portfolioAccounts()) {
            const option = document.createElement("option");
            option.value = String(account.id);
            option.textContent = `${account.name} (${account.base_currency})`;
            select.appendChild(option);
        }
    }

    async function loadAccounts() {
        const result = await request(API.accounts);
        if (!Array.isArray(result)) {
            throw new Error("The accounts API returned an unexpected response.");
        }

        accounts = result;
        fillAccountSelect($("account-transaction-account"), "Choose an account");
        fillAccountSelect($("account-transaction-filter-account"), "All accounts");
    }

    async function loadWalletCash() {
        const messageId = "wallet-cash-message";

        try {
            const result = await request(API.walletCash);
            const rows = Array.isArray(result.items) ? result.items : [];

            for (const row of rows) {
                const input = $(`wallet-cash-${row.account_id}`);
                if (input) input.value = Number(row.cash_balance ?? 0).toFixed(2);
            }

            showMessage(messageId, "");
        } catch (error) {
            showMessage(messageId, `Could not load wallet cash: ${error.message}`, true);
        }
    }

    async function saveWalletCash(event) {
        event.preventDefault();

        const button = $("save-wallet-cash");
        const values = [
            { accountId: 1, input: $("wallet-cash-1") },
            { accountId: 2, input: $("wallet-cash-2") }
        ];

        for (const item of values) {
            const value = Number(item.input.value);

            if (!Number.isFinite(value) || value < 0 ||
                Math.round(value * 100) !== value * 100) {
                showMessage("wallet-cash-message",
                    "Enter valid non-negative cash balances with at most two decimal places.", true);
                item.input.focus();
                return;
            }
        }

        button.disabled = true;
        showMessage("wallet-cash-message", "Saving wallet cash...");

        try {
            // Save each account independently so an error can identify the affected account.
            for (const item of values) {
                await request(`${API.walletCash}/${item.accountId}`, {
                    method: "PUT",
                    body: JSON.stringify({
                        cash_balance: Number(item.input.value)
                    })
                });
            }

            showMessage("wallet-cash-message", "Wallet cash saved successfully.");
        } catch (error) {
            showMessage(
                "wallet-cash-message",
                `Could not save all wallet balances: ${error.message}. Check both balances before retrying.`,
                true
            );
            await loadWalletCash();
        } finally {
            button.disabled = false;
        }
    }

    function getTransactionFilters() {
        const params = new URLSearchParams({
            page: String(currentPage),
            page_size: String(PAGE_SIZE)
        });

        const accountId = $("account-transaction-filter-account").value;
        const type = $("account-transaction-filter-type").value;

        if (accountId) params.set("account_id", accountId);
        if (type) params.set("transaction_type", type);

        return params;
    }

    function renderTransaction(row) {
        const currency = row.currency || "INR";
        const type = String(row.transaction_type || "").toUpperCase();
        const typeLabel = type === "DEPOSIT" ? "Deposit" : "Withdrawal";
        const sign = type === "WITHDRAWAL" ? "−" : "+";

        return `
            <tr>
                <td>${escapeHtml(row.transaction_date || "—")}</td>
                <td>${escapeHtml(row.account_name || "—")}</td>
                <td><span class="transaction-type">${escapeHtml(typeLabel)}</span></td>
                <td class="numeric-cell">${escapeHtml(sign + formatAmount(row.amount, currency))}</td>
                <td>${escapeHtml(row.reference || "—")}</td>
                <td>${escapeHtml(row.description || "—")}</td>
                <td>
                    <div class="transaction-row-actions">
                        <button type="button" class="secondary-button"
                                data-account-edit="${Number(row.transaction_id)}">Edit</button>
                        <button type="button" class="secondary-button"
                                data-account-delete="${Number(row.transaction_id)}">Delete</button>
                    </div>
                </td>
            </tr>`;
    }

    async function loadTransactions() {
        if (loadingTransactions) return;
        loadingTransactions = true;

        const message = $("account-transaction-message");
        message.textContent = "Loading account transactions...";
        tableBody.innerHTML = '<tr><td colspan="7">Loading account transactions...</td></tr>';

        try {
            const params = getTransactionFilters();
            const result = await request(`${API.transactions}?${params.toString()}`);

            const rows = Array.isArray(result.items) ? result.items : [];
            currentPage = Number(result.page) || 1;
            totalPages = Math.max(1, Number(result.total_pages) || 1);

            tableBody.innerHTML = rows.length
                ? rows.map(renderTransaction).join("")
                : '<tr><td colspan="7">No account transactions found.</td></tr>';

            $("account-transaction-count").textContent = String(result.total ?? rows.length);
            $("account-transaction-page-summary").textContent =
                `${currentPage} of ${totalPages}`;
            $("account-transaction-page-label").textContent =
                `Page ${currentPage} of ${totalPages}`;
            $("account-transaction-previous").disabled = currentPage <= 1;
            $("account-transaction-next").disabled = currentPage >= totalPages;

            message.textContent = rows.length
                ? `${rows.length} transaction(s) on this page.`
                : "No matching account transactions.";
        } catch (error) {
            tableBody.innerHTML =
                '<tr><td colspan="7">Could not load account transactions.</td></tr>';
            message.textContent = `Could not load account transactions: ${error.message}`;
        } finally {
            loadingTransactions = false;
        }
    }

    function resetForm() {
        editingId = null;
        form.reset();
        $("account-transaction-date").value = todayLocal();
        $("account-transaction-form-message").textContent = "";
        $("save-account-transaction").textContent = "Save transaction";
        $("toggle-account-transaction-form").textContent = "Add transaction";
        form.hidden = true;
    }

    function openNewForm() {
        // The same button opens the form and closes it, including during editing.
        if (!form.hidden) {
            resetForm();
            return;
        }

        editingId = null;
        form.reset();
        $("account-transaction-date").value = todayLocal();
        $("account-transaction-form-message").textContent = "";
        $("save-account-transaction").textContent = "Save transaction";
        form.hidden = false;
        $("toggle-account-transaction-form").textContent = "Close form";
    }

    async function editTransaction(id) {
        try {
            const result = await request(
                `${API.transactions}?${getTransactionFilters().toString()}`
            );
            const selected = (result.items || []).find(
                (item) => Number(item.transaction_id) === id
            );

            if (!selected) {
                throw new Error("Transaction not found. Refresh the transaction list and try again.");
            }

            editingId = id;
            $("account-transaction-account").value = String(selected.account_id);
            $("account-transaction-date").value = String(selected.transaction_date).slice(0, 10);
            $("account-transaction-type").value = selected.transaction_type;
            $("account-transaction-amount").value = Number(selected.amount).toFixed(2);
            $("account-transaction-reference").value = selected.reference || "";
            $("account-transaction-description").value = selected.description || "";
            $("account-transaction-form-message").textContent = "";
            $("save-account-transaction").textContent = "Update transaction";
            $("toggle-account-transaction-form").textContent = "Close form";
            form.hidden = false;
            form.scrollIntoView({ behavior: "smooth", block: "start" });
        } catch (error) {
            showMessage("account-transaction-message", error.message, true);
        }
    }

    async function saveTransaction(event) {
        event.preventDefault();

        const button = $("save-account-transaction");
        const amount = Number($("account-transaction-amount").value);

        if (!Number.isFinite(amount) || amount <= 0) {
            showMessage("account-transaction-form-message", "Amount must be greater than zero.", true);
            return;
        }

        const payload = {
            account_id: Number($("account-transaction-account").value),
            transaction_date: $("account-transaction-date").value,
            transaction_type: $("account-transaction-type").value,
            amount,
            reference: $("account-transaction-reference").value.trim(),
            description: $("account-transaction-description").value.trim()
        };

        button.disabled = true;
        showMessage("account-transaction-form-message", "Saving transaction...");

        try {
            const url = editingId === null
                ? API.transactions
                : `${API.transactions}/${editingId}`;

            await request(url, {
                method: editingId === null ? "POST" : "PUT",
                body: JSON.stringify(payload)
            });

            resetForm();
            currentPage = 1;
            await loadTransactions();
        } catch (error) {
            showMessage("account-transaction-form-message", error.message, true);
        } finally {
            button.disabled = false;
        }
    }

    async function deleteTransaction(id) {
        const row = tableBody.querySelector(`[data-account-delete="${id}"]`)?.closest("tr");
        const summary = row ? row.cells[1].textContent : "this account transaction";

        if (!window.confirm(`Delete the transaction for ${summary}? This cannot be undone.`)) {
            return;
        }

        try {
            await request(`${API.transactions}/${id}`, { method: "DELETE" });
            await loadTransactions();
        } catch (error) {
            showMessage("account-transaction-message",
                `Could not delete transaction: ${error.message}`, true);
        }
    }

    $("wallet-cash-form").addEventListener("submit", saveWalletCash);
    form.addEventListener("submit", saveTransaction);

    $("toggle-account-transaction-form").addEventListener("click", openNewForm);
    $("cancel-account-transaction-form").addEventListener("click", resetForm);

    $("account-transaction-filters").addEventListener("submit", (event) => {
        event.preventDefault();
        currentPage = 1;
        loadTransactions();
    });

    $("reset-account-transaction-filters").addEventListener("click", () => {
        $("account-transaction-filter-account").value = "";
        $("account-transaction-filter-type").value = "";
        currentPage = 1;
        loadTransactions();
    });

    $("account-transaction-previous").addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage -= 1;
            loadTransactions();
        }
    });

    $("account-transaction-next").addEventListener("click", () => {
        if (currentPage < totalPages) {
            currentPage += 1;
            loadTransactions();
        }
    });

    tableBody.addEventListener("click", (event) => {
        const editButton = event.target.closest("[data-account-edit]");
        const deleteButton = event.target.closest("[data-account-delete]");

        if (editButton) editTransaction(Number(editButton.dataset.accountEdit));
        if (deleteButton) deleteTransaction(Number(deleteButton.dataset.accountDelete));
    });

    async function initialize() {
        try {
            await loadAccounts();
        } catch (error) {
            showMessage("account-transaction-message",
                `Could not load account choices: ${error.message}`, true);
        }

        await loadWalletCash();
        await loadTransactions();
    }

    initialize();
})();
