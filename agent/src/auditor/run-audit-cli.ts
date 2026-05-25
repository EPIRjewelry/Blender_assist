import { auditCurrentJob } from "./run-audit.js";

auditCurrentJob().catch((err) => {
  console.error(err);
  process.exit(1);
});
