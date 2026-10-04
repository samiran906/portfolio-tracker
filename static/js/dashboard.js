async function loadPortfolioSummary() {
    const status = document.getElementById("status");
    const errorMessage = document.getElementById("error-message");

    try {
        status.textContent = "Loading...";

        const response = await fetch("/api/portfolio/summary");

        if (!response.ok) {
            throw new Error(`API returned HTTP ${response.status}`);
        }

        const data = await response.json();

        document.getElementById("valuation-date").textContent =
            formatDate(data.valuation_date);

        document.getElementById("portfolio-value").textContent =
            formatCurrency(data.total_portfolio_value);

        document.getElementById("securities-value").textContent =
            formatCurrency(data.total_securities_value);

        document.getElementById("cash-value").textContent =
            formatCurrency(data.total_cash);

        document.getElementById("cost-value").textContent =
            formatCurrency(data.total_cost_value);

        document.getElementById("pnl-value").textContent =
            formatCurrency(data.total_unrealized_pnl);

        document.getElementById("pnl-percent").textContent =
            formatPercent(data.unrealized_pnl_percent);

        document.getElementById("xirr-value").textContent =
            formatPercent(data.portfolio_xirr_percent);

        status.textContent = "Updated";

        errorMessage.classList.add("hidden");
        errorMessage.textContent = "";

    } catch (error) {
        console.error("Failed to load portfolio summary:", error);

        status.textContent = "Unavailable";

        errorMessage.textContent =
            "Unable to load portfolio data. Please check the API service.";

        errorMessage.classList.remove("hidden");
    }
}


function formatCurrency(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(number);
}


function formatPercent(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return `${number.toFixed(2)}%`;
}


function formatDate(value) {
    if (!value) {
        return "—";
    }

    const date = new Date(`${value}T00:00:00`);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return date.toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric"
    });
}


document.addEventListener("DOMContentLoaded", loadPortfolioSummary);
