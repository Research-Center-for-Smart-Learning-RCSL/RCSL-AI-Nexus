import { Button } from '@/components/ui/button';
import { DialogFooter } from '@/components/ui/dialog';
import { OneTimeSecret } from '@/components/composed/one-time-secret';
import { IntegrationSnippet } from '@/features/gateway/components/integration-snippet';

export function IssuedApiKeySecret({
  plaintext,
  capability,
  acknowledged,
  setAcknowledged,
  close,
}: {
  plaintext: string;
  capability: string;
  acknowledged: boolean;
  setAcknowledged: (acknowledged: boolean) => void;
  close: () => void;
}) {
  return (
    <>
      <div className="max-h-[60vh] space-y-5 overflow-y-auto overscroll-contain">
        <OneTimeSecret
          title="The key, shown once"
          description="Only a peppered hash is stored, so this cannot be retrieved later. If it is lost, revoke and issue a new one."
          values={[plaintext]}
          acknowledgement="I have saved this key"
          onAcknowledgedChange={setAcknowledged}
        />
        <IntegrationSnippet plaintext={plaintext} capability={capability} />
      </div>
      <DialogFooter>
        <Button disabled={!acknowledged} onClick={close}>
          Done
        </Button>
      </DialogFooter>
    </>
  );
}
