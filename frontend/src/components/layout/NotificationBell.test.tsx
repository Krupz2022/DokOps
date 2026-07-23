// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import NotificationBell from "./NotificationBell";

vi.mock("../../lib/api", () => ({
  listNotifications: vi.fn().mockResolvedValue([
    {
      id: 1,
      status: "succeeded",
      message: "deployment/x is up",
      read: false,
      conversation_id: "c1",
      target: "deployment/x",
      namespace: "default",
      created_at: new Date().toISOString(),
    },
  ]),
  markNotificationRead: vi.fn().mockResolvedValue(undefined),
  markAllNotificationsRead: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../context/ChatContext", () => ({
  useChatContext: () => ({
    setPanelOpen: vi.fn(),
    loadConversation: vi.fn(),
  }),
}));

describe("NotificationBell", () => {
  it("shows an unread count badge", async () => {
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
  });
});
