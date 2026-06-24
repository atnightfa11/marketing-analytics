import { defineConfig } from "cypress";

export default defineConfig({
  e2e: {
    baseUrl: "http://127.0.0.1:4173",
    specPattern: "tests/**/*.cy.ts",
    supportFile: false,
    video: false,
    screenshotOnRunFailure: false,
  },
});
