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

  it("acknowledges alerts", () => {
    cy.contains("Recent Alerts").should("exist");
  });

  it("shows privacy controls", () => {
    cy.visit("http://localhost:5173/settings");
    cy.contains("Privacy Controls").should("exist");
  });
});
