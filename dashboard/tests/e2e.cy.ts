describe("Marketing Analytics Dashboard", () => {
  beforeEach(() => {
    cy.visit("http://localhost:5173");
  });

  it("renders KPI grid", () => {
    cy.contains("Daily Uniques").should("exist");
  });

  it("shows forecast bounds", () => {
    cy.contains("Forecast").should("exist");
  });

  it("does not expose the old static alerts page", () => {
    cy.visit("http://localhost:5173/alerts");
    cy.location("pathname").should("eq", "/");
  });

  it("shows privacy controls", () => {
    cy.visit("http://localhost:5173/settings");
    cy.contains("Privacy Controls").should("exist");
  });
});
