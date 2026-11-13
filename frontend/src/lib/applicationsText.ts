// Plain wording for the administrator's business-application screens.
export function waitingText(count: number): string {
  return count === 1 ? '1 business application is waiting for your decision.' : `${count} business applications are waiting for your decision.`;
}

const STATUS: Record<string, string> = {
  PENDING_REVIEW: 'Waiting for your decision', NEEDS_INFORMATION: 'Waiting for the applicant', APPROVED: 'Approved',
  REJECTED: 'Not approved', EXPIRED: 'Expired', CANCELLED: 'Withdrawn',
};
export const statusText = (status: string): string => STATUS[status] || status.replaceAll('_', ' ').toLowerCase();

export type Decision = 'approve' | 'request_information' | 'reject' | 'note' | 'expire';

/** What must be true before a decision can be sent; returns a message to show, or '' when it may proceed. */
export function decisionProblem(decision: Decision, message: string): string {
  if (decision === 'request_information' && !message.trim()) return 'Write what you need from the applicant first. It is sent to them.';
  return '';
}

export function decisionNotice(decision: Decision, name: string): string {
  if (decision === 'approve') return `${name} is approved. They have been told and can now choose a plan and pay.`;
  if (decision === 'reject') return `${name} was not approved. They have been told.`;
  if (decision === 'request_information') return `Your question was sent to ${name}. The application waits for their reply.`;
  if (decision === 'expire') return `${name}'s application is marked expired.`;
  return 'Private note saved. The applicant was not contacted.';
}
