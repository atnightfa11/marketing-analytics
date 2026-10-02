describe("Plan capacity and predictable billing", () => {
  function stubAccount(owner = true, plan = "standard", usageFails = false) {
    cy.intercept("**/api/**", (req) => {
      const path = new URL(req.url).pathname;
      if (path === "/api/auth/status") return req.reply({ enabled: false });
      if (path === "/api/sites") return req.reply({ sites: [{ site_id: "capacity-test", site_name: "Capacity test", plan }] });
      if (path === "/api/site-settings") return req.reply({ site_id: "capacity-test", site_name: "Capacity test", timezone: "UTC" });
      if (path === "/api/billing/status") return req.reply({
        site_id: "capacity-test", plan, display_plan: plan === "free" ? "Solo" : "Standard",
        has_subscription: true, can_manage_billing: owner, is_billing_owner: owner,
        payment_status: "ok", included_sites: 3, owned_site_count: 1, additional_site_count: 0,
        can_manage_site_access: true, can_manage_anomaly_alerts: true, can_import_historical_data: true,
      });
      if (path === "/api/billing/usage") {
        if (usageFails) return req.reply(503, { detail: "Unavailable" });
        return req.reply({
          plan, total_pageview_capacity: plan === "free" ? 100_000 : 1_000_000,
          additional_million_price_usd: 15, can_request_capacity: plan === "standard",
          ambiguous_subscriptions: false, automatic_billing: false, pending_request: null,
          current_period: { period_start: "2026-10-01T00:00:00Z", period_end: "2026-11-01T00:00:00Z",
            first_recorded_at: "2026-10-02T12:00:00Z", period_basis: "stripe_period", accepted_pageviews: 1_200_000 },
        });
      }
      req.reply(404, { detail: "Not needed for billing test" });
    });
  }

  it("shows partial usage and submits a request without creating a checkout", () => {
    stubAccount();
    cy.intercept("POST", "**/api/billing/capacity-request", (req) => {
      expect(req.body).to.deep.equal({ site_id: "capacity-test", additional_millions: 2 });
      req.reply({ request_id: "request-test", additional_millions: 2, monthly_price_usd: 30, status: "pending" });
    }).as("requestCapacity");
    cy.visit("/site/capacity-test/settings?panel=billing");
    cy.contains("No automatic overage charges.").should("be.visible");
    cy.contains("counts may be partial").should("be.visible");
    cy.get("#capacity-millions").clear().type("2");
    cy.contains("+$30/month, before tax.").should("be.visible");
    cy.contains("button", "Request capacity").click();
    cy.wait("@requestCapacity");
    cy.contains("Awaiting review; your subscription has not changed.").should("be.visible");
    cy.get("#capacity-millions").should("not.exist");
  });

  it("routes an existing Solo subscriber to billing management", () => {
    stubAccount(true, "free");
    cy.visit("/site/capacity-test/settings?panel=billing");
    cy.contains("button", "Manage plan & billing").should("be.enabled");
    cy.contains("button", "Upgrade To Standard").should("not.exist");
    cy.get("#capacity-millions").should("not.exist");
  });

  it("keeps account usage and billing controls away from members", () => {
    stubAccount(false);
    cy.visit("/site/capacity-test/settings?panel=billing");
    cy.contains("Current plan:").should("be.visible");
    cy.contains("Account pageviews").should("not.exist");
    cy.get("#billing button").first().should("be.disabled");
  });

  it("offers retry for usage failures on a narrow screen", () => {
    stubAccount(true, "standard", true);
    cy.viewport(390, 844);
    cy.visit("/site/capacity-test/settings?panel=billing");
    cy.contains("Usage is unavailable. Your subscription has not changed.").should("be.visible");
    cy.contains("button", "Refresh").should("be.enabled");
    cy.document().then((doc) => expect(doc.documentElement.scrollWidth).to.be.at.most(390));
  });
});
