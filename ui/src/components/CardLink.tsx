import {
  FloatingPortal,
  autoUpdate,
  flip,
  offset,
  shift,
  useDismiss,
  useFloating,
  useFocus,
  useHover,
  useInteractions,
  useRole,
} from '@floating-ui/react';
import { useEffect, useState, type AnchorHTMLAttributes, type ReactNode } from 'react';
import {
  cachedCardPreviewOrientation,
  cardPreviewImageUrl,
  loadCardPreviewOrientation,
  previewImageHasFailed,
  rememberFailedPreviewImage,
} from '../cardPreview';
import { formatCardName } from '../format';
import { cardRouteHash } from '../routes';

interface CardLinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  cardName: string;
  children?: ReactNode;
  returnHash?: string;
}

function CardLinkPreview({
  cardName,
  children,
  className,
  returnHash,
  ...anchorProps
}: CardLinkProps) {
  const previewUrl = cardPreviewImageUrl(cardName);
  const displayName = formatCardName(cardName);
  const [open, setOpen] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageFailed, setImageFailed] = useState(() => previewImageHasFailed(previewUrl));
  const [orientation, setOrientation] = useState(() => cachedCardPreviewOrientation(cardName));
  const {
    context,
    floatingStyles,
    refs: { setFloating, setReference },
  } = useFloating({
    open,
    onOpenChange: setOpen,
    placement: 'right-start',
    middleware: [offset(10), flip({ padding: 12 }), shift({ padding: 12 })],
    whileElementsMounted: autoUpdate,
  });
  const hover = useHover(context, {
    delay: { open: 180, close: 80 },
    mouseOnly: true,
  });
  const focus = useFocus(context);
  const dismiss = useDismiss(context);
  const role = useRole(context, { role: 'tooltip' });
  const { getFloatingProps, getReferenceProps } = useInteractions([
    hover,
    focus,
    dismiss,
    role,
  ]);

  useEffect(() => {
    if (!open || !cardName.includes('//')) {
      return;
    }
    const controller = new AbortController();
    void loadCardPreviewOrientation(cardName, controller.signal)
      .then(setOrientation)
      .catch((error: unknown) => {
        if (!(error instanceof Error && error.name === 'AbortError')) {
          setOrientation('portrait');
        }
      });
    return () => controller.abort();
  }, [cardName, open]);

  return (
    <>
      <a
        ref={setReference}
        className={['card-link', className].filter(Boolean).join(' ')}
        href={cardRouteHash(cardName, returnHash)}
        {...getReferenceProps(anchorProps)}
      >
        {children ?? displayName}
      </a>
      {open ? (
        <FloatingPortal>
          <div
            ref={setFloating}
            className={orientation === 'landscape' ? 'card-preview card-preview-landscape' : 'card-preview'}
            data-card-name={cardName}
            data-card-orientation={orientation}
            style={floatingStyles}
            {...getFloatingProps()}
          >
            <div className="card-preview-media">
              {imageFailed ? (
                <div className="card-preview-fallback">
                  <strong>{displayName}</strong>
                  <span>Card image unavailable</span>
                </div>
              ) : (
                <>
                  {!imageLoaded ? <div className="card-preview-loading">Loading card...</div> : null}
                  <img
                    className={imageLoaded ? 'card-preview-image card-preview-image-loaded' : 'card-preview-image'}
                    src={previewUrl}
                    alt={`${displayName} card preview`}
                    onLoad={() => setImageLoaded(true)}
                    onError={() => {
                      rememberFailedPreviewImage(previewUrl);
                      setImageFailed(true);
                    }}
                  />
                </>
              )}
            </div>
          </div>
        </FloatingPortal>
      ) : null}
    </>
  );
}

export function CardLink(props: CardLinkProps) {
  return <CardLinkPreview key={props.cardName} {...props} />;
}
