# Suite 1 - Onboarding & first build

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** The first ten minutes decide whether a customer stays. A new person arrives knowing only that "this builds apps with AI" - and they need to go from a sign-up form to *understanding the product and being ready to create something* without getting lost, stuck, or confused. This suite is about the **experience** of arriving: is signing up quick and reassuring, does sign-in with Google/GitHub just work, can someone who forgot their password get back in, and - most importantly - once they're in, does the product explain itself and guide them toward their first real action. We are not testing auth security here (the automated suites cover that); we are testing whether onboarding *feels* welcoming and lands the customer somewhere they can succeed.

**Suite prerequisites:** A fresh, unused email inbox (two if possible). A Google account and a GitHub account available for OAuth cases. Test against the QA/staging URL - do not test against production. Run these on a clean browser profile (no existing session) so you experience onboarding as a true first-time user.

---

### `ONBOARD-01` - Sign up and reach the product
- **Customer value:** A brand-new person can create an account and land inside Tesslate Studio, ready to use it.
- **Priority:** Critical
- **Pre:** Logged out, clean browser profile. An unused, valid email address.
- **Scenario:**
  1. Open the sign-up page and fill in the required details (email, name, password, etc.).
  2. Submit and follow whatever the product asks next - email verification, a welcome step, etc.
  3. If a verification email is sent, open it and complete the link.
  4. Continue until you are inside the actual product (dashboard / home).
- **What good looks like:**
  - The sign-up form is short, clear, and obvious about what each field needs.
  - Account creation feels fast - no long unexplained spinner.
  - Any verification email arrives within a minute or two and the link works first try.
  - You end up *inside the product* on a real landing surface - not stranded on a "check your email" dead end or a blank page.
  - At no point are you confused about what to do next.
- **Watch for:** verification email never arriving or going to spam; the link erroring; ending up logged out after verifying; a jarring jump between pages; raw error text on any misstep.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ONBOARD-02` - Sign in with Google
- **Customer value:** A customer who would rather not manage another password can join and sign in with one click.
- **Priority:** High
- **Pre:** Logged out; a Google account not yet used with Tesslate Studio.
- **Scenario:**
  1. On the sign-in page, choose "Continue with Google".
  2. Complete the Google consent screen.
  3. Observe where you land.
- **What good looks like:**
  - The Google handoff and return are quick and seamless.
  - A new account is created with your name/email pre-filled - no second form to re-type what Google already provided.
  - You land inside the product, fully signed in.
  - Signing out and back in via Google returns you to the *same* account, not a duplicate.
- **Watch for:** the return loop hanging; landing on a half-filled form; a duplicate account being created on a second sign-in; an error if the Google account has no public name.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ONBOARD-03` - Sign in with GitHub
- **Customer value:** A developer-customer can join with the account they already use for their code.
- **Priority:** High
- **Pre:** Logged out; a GitHub account not yet used with Tesslate Studio.
- **Scenario:**
  1. On the sign-in page, choose "Continue with GitHub".
  2. Authorize the application on GitHub.
  3. Observe where you land.
- **What good looks like:**
  - The GitHub authorization and return are quick and seamless.
  - A new account is created with details pulled from GitHub.
  - You land inside the product, signed in.
  - It still works for a GitHub account whose email is private.
- **Watch for:** the return loop hanging; an error when the GitHub email is hidden; a duplicate account on repeat sign-in.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ONBOARD-04` - Recover a forgotten password
- **Customer value:** A returning customer who forgot their password can get back into their account without contacting support.
- **Priority:** Critical
- **Pre:** A registered email/password account exists; you are logged out.
- **Scenario:**
  1. From the sign-in page, choose "Forgot password?".
  2. Enter the account's email and submit.
  3. Open the reset email, click the link, and set a new password.
  4. Sign in with the new password.
- **What good looks like:**
  - The reset flow is easy to find and reassuring - it tells you to check your email.
  - The reset email arrives within a minute or two; the link is clearly a "reset your password" message.
  - Setting the new password is straightforward and confirms success.
  - You can immediately sign in with the new password; the old one no longer works.
  - The whole recovery takes a couple of minutes, not a frustrating ordeal.
- **Watch for:** the email not arriving; the link being expired on first use; no confirmation after setting the new password; being bounced back to sign-in with no indication it worked.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ONBOARD-05` - First-time guidance: I understand what to do
- **Customer value:** Right after signing up, the customer understands what Tesslate Studio is and how to start - without reading docs or guessing.
- **Priority:** High
- **Pre:** A brand-new account (from `ONBOARD-01`), seeing the product for the very first time.
- **Scenario:**
  1. Land on the post-signup home/dashboard and pause - read the screen as a first-timer would.
  2. Note any welcome message, tour, sample content, or "get started" guidance.
  3. Look for the most obvious next action.
- **What good looks like:**
  - The landing screen makes the product's purpose clear - you can tell this is where you build apps by describing them.
  - There is an unmistakable primary call to action (e.g. "Create your first project" / "New project").
  - The empty state is welcoming, not a blank or broken-looking page.
  - Any onboarding tour or tips are helpful and skippable, not nagging.
  - Within ~30 seconds of landing you know what to click next.
- **Watch for:** a bare empty dashboard with no guidance; a tour that traps you or can't be dismissed; jargon that assumes prior knowledge; a primary action that's hard to spot.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ONBOARD-06` - From signed-up to about-to-build
- **Customer value:** The customer can move smoothly from "just signed up" to the point of actually creating something, without dead ends.
- **Priority:** High
- **Pre:** A new account on the home/dashboard (`ONBOARD-05`).
- **Scenario:**
  1. Click the primary "create" action.
  2. Follow the project-creation flow up to the point just before committing (naming, picking a starting point, etc.).
  3. Note how guided and confident the path feels - do not finish creation here (suite 2 covers that).
- **What good looks like:**
  - The path from dashboard to the creation flow is one obvious click.
  - The creation flow explains the options (empty, template, import) clearly enough for a first-timer to choose.
  - At every step you know where you are and how to go back.
  - Nothing blocks a brand-new account from reaching the creation flow (no surprise "verify first" or "set up billing first" wall for a basic free action).
- **Watch for:** the create action being hidden or disabled with no explanation; an overwhelming options screen; the flow stalling or looping; an unexpected paywall before the first project.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ONBOARD-07` - The product feels oriented, not overwhelming
- **Customer value:** A first-time customer can find their way around - they see where projects, the agent, settings, and help live.
- **Priority:** Medium
- **Pre:** A new account, signed in, exploring for the first time.
- **Scenario:**
  1. Look over the main navigation and overall layout.
  2. Identify where you'd go to: see your projects, change settings, find help/docs, and sign out.
  3. Click into one or two non-destructive areas and come back.
- **What good looks like:**
  - Navigation is clear and consistently placed; key destinations are labelled in plain language.
  - The layout feels calm and intentional, not cluttered or half-loaded.
  - Help, docs, or support is discoverable for a stuck newcomer.
  - Moving between areas and back is smooth, with no broken or empty screens.
- **Watch for:** mystery icons with no labels; navigation that shifts or flickers on load; no visible path to help; areas that look unfinished.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ONBOARD-08` - Welcome email and account confirmation
- **Customer value:** A new customer gets a clear signal that their account is real and set up, and knows how to get back to it.
- **Priority:** Low
- **Pre:** A freshly created account (`ONBOARD-01`); access to its inbox.
- **Scenario:**
  1. Check the inbox for any welcome / getting-started email after signup.
  2. Open it and follow any links back to the product.
- **What good looks like:**
  - If a welcome email is sent, it is well-formatted, on-brand, and free of broken images or placeholder text.
  - Links in it lead to the right places and work.
  - It helps a newcomer return and get started, rather than feeling like spam.
- **Watch for:** broken layout or `{{placeholder}}` tokens; dead links; the email landing in spam; (if no welcome email is intended, this case still passes - note that).
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

---

## Suite roll-up

| Result | Count |
|--------|-------|
| Pass | |
| Fail | |
| Blocked | |
| Not run | |

**Defects filed:** _list IDs_ - 
**Overall onboarding experience (1-5) & notes:** 
