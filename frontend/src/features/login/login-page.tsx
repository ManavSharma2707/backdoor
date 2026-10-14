import { useEffect, useState } from "react";
import { useLocation } from "react-router";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { api, isApiError, wakeServer } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { common } from "@/copy/common";
import { login as copy } from "@/copy/login";
import type { AuthConfig } from "@/types/models";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { Banner } from "@/components/ui/display";

const schema = z.object({
  email: z.string().trim().min(1, copy.emailRequired).email(copy.emailInvalid),
  password: z.string().min(1, copy.passwordRequired),
});
type Values = z.infer<typeof schema>;

export function waitText(seconds: number): string {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  return seconds < 60 ? common.time.seconds(Math.max(1, seconds)) : common.time.minutes(minutes);
}

export function loginErrorText(error: unknown): string {
  if (isApiError(error)) {
    if (error.code === "NETWORK") return common.errors.network;
    if (error.retryAfter) return copy.locked(waitText(error.retryAfter));
    if (error.code === "RATE_LIMITED") return copy.locked(common.time.minutes(1));
    if (error.status === 401) return copy.wrong;
    return error.message;
  }
  return common.errors.server;
}

export default function LoginPage() {
  const { login, demoLogin } = useAuth();
  const location = useLocation();
  const expired = Boolean((location.state as { expired?: boolean } | null)?.expired);
  const [showPassword, setShowPassword] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [slow, setSlow] = useState(false);
  const [busyDemo, setBusyDemo] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setFocus,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), mode: "onBlur" });

  const config = useQuery({
    queryKey: ["auth-config"],
    queryFn: () => api<AuthConfig>("/auth/config", { anonymous: true }),
    retry: false,
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    void wakeServer();
    setFocus("email");
  }, [setFocus]);

  const pending = isSubmitting || busyDemo !== null;
  useEffect(() => {
    if (!pending) {
      setSlow(false);
      return;
    }
    const timer = setTimeout(() => setSlow(true), 3000);
    return () => clearTimeout(timer);
  }, [pending]);

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login(values.email.trim(), values.password);
    } catch (error) {
      setFormError(loginErrorText(error));
    }
  });

  const onDemo = async (key: string) => {
    setFormError(null);
    setBusyDemo(key);
    try {
      await demoLogin(key);
    } catch (error) {
      setFormError(loginErrorText(error));
      setBusyDemo(null);
    }
  };

  const profiles = config.data?.demo_login_enabled ? config.data.demo_profiles : [];

  return (
    <main className="min-h-dvh bg-bg px-4 pt-[18vh] pb-12 md:px-12">
      <div className="w-full max-w-[360px]">
        <h1 className="text-xl font-semibold">{common.appName}</h1>
        <p className="mt-1 text-base text-text-2">{copy.title}</p>

        {expired ? (
          <Banner tone="warning" className="mt-5">
            {copy.sessionEnded}
          </Banner>
        ) : null}

        <form onSubmit={onSubmit} noValidate className="mt-6 space-y-4">
          <Field label={copy.email} error={errors.email?.message}>
            {(ids) => (
              <Input {...ids} type="email" autoComplete="username" {...register("email")} />
            )}
          </Field>
          <Field label={copy.password} error={errors.password?.message}>
            {(ids) => (
              <div className="relative">
                <Input
                  {...ids}
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  className="pr-16"
                  {...register("password")}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-pressed={showPassword}
                  className="absolute inset-y-0 right-0 rounded-sm px-3 text-sm font-medium text-link"
                >
                  {showPassword ? copy.hidePassword : copy.showPassword}
                </button>
              </div>
            )}
          </Field>
          <Button
            type="submit"
            variant="primary"
            size="lg"
            className="w-full"
            loading={isSubmitting}
          >
            {copy.submit}
          </Button>
          <div aria-live="polite" className="space-y-2">
            {formError ? (
              <p role="alert" className="text-base text-critical">
                {formError}
              </p>
            ) : null}
            {slow ? <p className="text-sm text-text-2">{copy.waking}</p> : null}
          </div>
        </form>

        {profiles.length > 0 ? (
          <div className="mt-8">
            <div className="flex items-center gap-3 text-sm text-text-2">
              <span className="h-px flex-1 bg-border" />
              {copy.demoDivider}
              <span className="h-px flex-1 bg-border" />
            </div>
            <ul className="mt-4 space-y-2">
              {profiles.map((profile) => (
                <li key={profile.key}>
                  <Button
                    className="w-full justify-start"
                    loading={busyDemo === profile.key}
                    disabled={pending}
                    onClick={() => void onDemo(profile.key)}
                  >
                    {profile.name}
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <p className="mt-8 text-xs text-text-3">{copy.demoFooter}</p>
      </div>
    </main>
  );
}
