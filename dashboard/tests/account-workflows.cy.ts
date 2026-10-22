describe("Password recovery", () => {
  beforeEach(() => {
    cy.intercept("**/api/auth/status", { enabled: true });
    cy.intercept("**/api/auth/me", { statusCode: 401, body: { detail: "Sign in" } });
  });

  it("offers recovery outside the login gate", () => {
    cy.intercept("POST", "**/api/auth/password-reset/request", { message: "If that email belongs to an account, a reset link will arrive shortly." }).as("resetRequest");
    cy.visit("/");
    cy.contains("Forgot password?").click();
    cy.get('input[type="email"]').type("owner@example.test");
    cy.contains("button", "Send reset link").click();
    cy.wait("@resetRequest").its("request.body").should("deep.equal", { email: "owner@example.test" });
    cy.get('[role="status"]').should("contain", "reset link");
  });

  it("removes the reset token from the address bar and renders on a narrow dark screen", () => {
    cy.viewport(390, 844);
    cy.intercept("POST", "**/api/auth/password-reset/confirm", (req) => {
      expect(req.body).to.deep.equal({ token: "secret-in-fragment", password: "new-password" });
      req.reply({ message: "Password updated. Sign in with your new password." });
    }).as("resetConfirm");
    cy.visit("/reset-password#token=secret-in-fragment", { onBeforeLoad(win) { win.localStorage.setItem("valid.theme", "dark"); } });
    cy.get('input[type="password"]').type("new-password");
    cy.location("hash").should("equal", "");
    cy.screenshot("password-reset-mobile");
    cy.contains("button", "Update password").click();
    cy.wait("@resetConfirm");
    cy.get('[role="status"]').should("contain", "Password updated");
    cy.document().then((doc) => expect(doc.documentElement.scrollWidth).to.be.at.most(390));
  });

  it("handles missing reset links", () => {
    cy.visit("/reset-password");
    cy.contains("This link is incomplete").should("be.visible");
    cy.contains("Request a new link").should("have.attr", "href", "/forgot-password");
  });
});

describe("Additional website setup", () => {
  beforeEach(() => {
    cy.intercept("**/api/auth/status", { enabled: true });
    cy.intercept("**/api/auth/me", { username: "owner" });
    cy.intercept("GET", "**/api/sites", { sites: [] });
    cy.intercept("GET", "**/api/sites/provisioning", { statusCode: 200, body: null });
  });

  it("requires explicit price approval and reuses the request on retry", () => {
    let requestId = "";
    cy.intercept("POST", "**/api/sites", (req) => {
      if (!requestId) requestId = req.body.request_id;
      expect(req.body.request_id).to.equal(requestId);
      if (!req.body.approved_monthly_increase_usd) {
        req.reply(409, { detail: "This website adds $5/month. Approve the increase to continue." });
      } else {
        expect(req.body.approved_monthly_increase_usd).to.equal(5);
        req.reply({ ...req.body, site_id: "live-fourth-test", status: "complete", site_key: "public-test-key" });
      }
    }).as("addWebsite");
    cy.visit("/sites/new");
    cy.contains("label", "Website name").find("input").type("Fourth site");
    cy.contains("label", "Domain").find("input").type("fourth.test");
    cy.contains("button", "Add website").click();
    cy.wait("@addWebsite");
    cy.contains("starting with my next invoice").should("be.visible");
    cy.screenshot("additional-site-approval-desktop");
    cy.get('input[type="checkbox"]').check();
    cy.contains("button", "Add website").click();
    cy.wait("@addWebsite");
    cy.contains("Install Valid").should("be.visible");
    cy.contains("pre", "data-valid-site-id=\"live-fourth-test\"").should("be.visible");
    cy.contains("Review installation").should("have.attr", "href", "/site/live-fourth-test/settings");
    cy.viewport(390, 844);
    cy.document().then((doc) => expect(doc.documentElement.scrollWidth).to.be.at.most(390));
    cy.screenshot("additional-site-install-mobile");
  });

  it("restores pending setup and prevents changes during recovery", () => {
    cy.intercept("GET", "**/api/sites/provisioning", { request_id: "same-request", site_name: "Pending", site_domain: "https://pending.test", status: "pending" });
    cy.visit("/sites/new");
    cy.contains("button", "Resume setup").should("be.enabled");
    cy.contains("label", "Website name").find("input").should("have.value", "Pending").and("have.attr", "readonly");
  });

  it("stops new setup when the pending-state check fails", () => {
    cy.intercept("GET", "**/api/sites/provisioning", { statusCode: 503, body: {} });
    cy.visit("/sites/new");
    cy.contains("Reload before continuing").should("be.visible");
    cy.contains("button", "Add website").should("be.disabled");
  });
});
