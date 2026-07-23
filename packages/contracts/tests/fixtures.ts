import type { ChatRequest, ChatSseEvent } from "../src/index.js";

export const ids = {
  request: "00000000-0000-4000-8000-000000000001",
  event: "00000000-0000-4000-8000-000000000002",
  conversation: "00000000-0000-4000-8000-000000000003",
  message: "00000000-0000-4000-8000-000000000004",
  citation: "00000000-0000-4000-8000-000000000005",
  document: "00000000-0000-4000-8000-000000000006",
  modelProfile: "00000000-0000-4000-8000-000000000007",
  sourceVersion: "00000000-0000-4000-8000-000000000008",
  chunk: "00000000-0000-4000-8000-000000000009",
} as const;

export const validChatRequest = {
  contract_version: "v1",
  widget_key: "public_widget_key_123456",
  visitor_session_id: "visitor_session_123",
  history: [
    { role: "user", content: "How do I reset the device?" },
    { role: "assistant", content: "Which model do you have?" },
  ],
  question: "How do I reset model A?",
} satisfies ChatRequest;

const commonData = {
  contract_version: "v1" as const,
  request_id: ids.request,
};

export const validSseEvents = [
  {
    event: "answer.delta",
    id: ids.event,
    data: { ...commonData, text: "Press and hold the reset button." },
  },
  {
    event: "citation",
    id: ids.event,
    data: {
      ...commonData,
      citation_id: ids.citation,
      document_id: ids.document,
      document_title: "Model A manual",
      source_url: "https://support.example.com/model-a",
      page_number: 12,
      heading: "Factory reset",
    },
  },
  {
    event: "abstention",
    id: ids.event,
    data: {
      ...commonData,
      reason: "insufficient_evidence",
      message: "I could not find enough information to answer that.",
      handoff: {
        label: "Contact support",
        url: "https://support.example.com/contact",
        email: null,
      },
    },
  },
  {
    event: "complete",
    id: ids.event,
    data: {
      ...commonData,
      status: "answered",
      conversation_id: ids.conversation,
      message_id: ids.message,
    },
  },
  {
    event: "error",
    id: ids.event,
    data: {
      ...commonData,
      error: {
        code: "SERVICE_UNAVAILABLE",
        message: "Support chat is temporarily unavailable.",
        retryable: true,
      },
    },
  },
] satisfies ChatSseEvent[];
