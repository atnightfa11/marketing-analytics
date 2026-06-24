describe("Marketing Analytics Dashboard", () => {
  const baseUrl = Cypress.env("DASHBOARD_URL") || "http://127.0.0.1:4173";

  beforeEach(() => {
    cy.visit(baseUrl);
  });

  it("renders the restricted dashboard sign-in screen", () => {
    cy.contains("Sign In").should("be.visible");
    cy.get('input[aria-label="Username"]').should("exist");
    cy.get('input[aria-label="Password"]').should("exist");
  });

  it("keeps site routes behind authentication", () => {
    cy.visit(`${baseUrl}/site/demo`);
    cy.contains("Dashboard access is restricted.").should("be.visible");
  });

  it("keeps settings behind authentication", () => {
    cy.visit(`${baseUrl}/settings`);
    cy.contains("Dashboard access is restricted.").should("be.visible");
  });
});
