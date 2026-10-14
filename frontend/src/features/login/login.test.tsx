import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { session } from "@/test/handlers";
import { renderRoute, mockSignedIn, mockSignedOut, waitForHeading } from "@/test/render";
import { loginErrorText, waitText } from "./login-page";
import { ApiError } from "@/lib/api";

const refused = (headers: Record<string, string> = {}, status = 401) =>
  HttpResponse.json(
    {
      error: {
        code: "UNAUTHENTICATED",
        message: "Email or password is not right.",
        details: [],
        request_id: "r1",
      },
    },
    { status, headers },
  );

async function signIn(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("Email"), "owner@demo.test");
  await user.type(screen.getByLabelText("Password"), "a-long-password");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("login", () => {
  it("shows plain validation messages before sending anything", async () => {
    mockSignedOut();
    const user = userEvent.setup();
    renderRoute("/login");
    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your email.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
  });

  it("signs in and lands on the overview", async () => {
    mockSignedOut();
    server.use(http.post("/api/v1/auth/login", () => HttpResponse.json(session)));
    const user = userEvent.setup();
    renderRoute("/login");
    await signIn(user);
    await waitForHeading("Overview");
  });

  it("says the email or password is not right", async () => {
    mockSignedOut();
    server.use(http.post("/api/v1/auth/login", () => refused()));
    const user = userEvent.setup();
    renderRoute("/login");
    await signIn(user);
    expect(await screen.findByText("Email or password is not right.")).toBeInTheDocument();
  });

  it("shows the lockout wait time from Retry-After", async () => {
    mockSignedOut();
    server.use(http.post("/api/v1/auth/login", () => refused({ "Retry-After": "900" })));
    const user = userEvent.setup();
    renderRoute("/login");
    await signIn(user);
    expect(
      await screen.findByText("Too many attempts. Try again in 15 minutes."),
    ).toBeInTheDocument();
  });

  it("explains a slow server after a few seconds", async () => {
    mockSignedOut();
    server.use(
      http.post("/api/v1/auth/login", async () => {
        await new Promise((resolve) => setTimeout(resolve, 3400));
        return HttpResponse.json(session);
      }),
    );
    const user = userEvent.setup();
    renderRoute("/login");
    await signIn(user);
    expect(
      await screen.findByText(
        "The server is waking up. This can take up to a minute.",
        {},
        { timeout: 4000 },
      ),
    ).toBeInTheDocument();
    await waitForHeading("Overview");
  }, 12000);

  it("hides the demo buttons unless the server allows them", async () => {
    mockSignedOut();
    renderRoute("/login");
    await screen.findByLabelText("Email");
    expect(screen.queryByText("Or look around with demo data")).not.toBeInTheDocument();
  });

  it("shows one button per demo business when allowed and signs in with it", async () => {
    mockSignedOut();
    server.use(
      http.get("/api/v1/auth/config", () =>
        HttpResponse.json({
          demo_login_enabled: true,
          demo_profiles: [
            { key: "fmcg_a", name: "Shree Sai Kirana and General Stores" },
            { key: "med_a", name: "Sanjivani Medical and General" },
          ],
        }),
      ),
      http.post("/api/v1/auth/demo-login", async ({ request }) => {
        expect(await request.json()).toEqual({ profile_key: "med_a" });
        return HttpResponse.json(session);
      }),
    );
    const user = userEvent.setup();
    renderRoute("/login");
    expect(await screen.findByText("Or look around with demo data")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Shree Sai Kirana and General Stores" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sanjivani Medical and General" }));
    await waitForHeading("Overview");
  });

  it("sends signed out visitors to login and back to where they were going", async () => {
    mockSignedOut();
    server.use(http.post("/api/v1/auth/login", () => HttpResponse.json(session)));
    const user = userEvent.setup();
    const { router } = renderRoute("/products?q=pepper");
    await screen.findByLabelText("Email");
    expect(router.state.location.pathname).toBe("/login");
    await signIn(user);
    await waitFor(() => expect(router.state.location.pathname).toBe("/products"));
    expect(router.state.location.search).toBe("?q=pepper");
  });

  it("restores a session from the refresh cookie", async () => {
    mockSignedIn();
    renderRoute("/");
    await waitForHeading("Overview");
  });

  it("keeps people who are signed in off the login page", async () => {
    mockSignedIn();
    const { router } = renderRoute("/login");
    await waitForHeading("Overview");
    expect(router.state.location.pathname).toBe("/");
  });
});

describe("login messages", () => {
  it("turns seconds and minutes into words", () => {
    expect(waitText(30)).toBe("30 seconds");
    expect(waitText(60)).toBe("1 minute");
    expect(waitText(61)).toBe("2 minutes");
    expect(waitText(900)).toBe("15 minutes");
  });
  it("maps every failure to plain text", () => {
    const make = (status: number, code: string, retryAfter: number | null = null) =>
      new ApiError({ status, code, message: "server text", retryAfter });
    expect(loginErrorText(make(401, "UNAUTHENTICATED"))).toBe("Email or password is not right.");
    expect(loginErrorText(make(429, "RATE_LIMITED"))).toBe(
      "Too many attempts. Try again in 1 minute.",
    );
    expect(loginErrorText(make(0, "NETWORK"))).toMatch(/could not reach the server/);
    expect(loginErrorText(new Error("x"))).toMatch(/Something went wrong on our side/);
  });
});
