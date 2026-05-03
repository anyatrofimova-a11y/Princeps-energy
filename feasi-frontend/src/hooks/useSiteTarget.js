import {useCallback} from 'react';
import {useSearchParams} from 'react-router-dom';

/**
 * URL-search-param-backed site target — what the user is currently looking
 * at: a parcel id and / or a picked map location.
 *
 * Wire format: `?parcel=<id>&lat=<f>&lng=<f>&pick=1`
 *
 * Replaces `parcelId` / `pickedLocation` / `pickMode` from SiteContext.
 * URL-bound so deep links work for the first time.
 */

export function useSiteTarget() {
  const [params, setParams] = useSearchParams();

  const parcelId = params.get('parcel') || '';
  const lat = parseFloat(params.get('lat'));
  const lng = parseFloat(params.get('lng'));
  const pickedLocation = Number.isFinite(lat) && Number.isFinite(lng)
    ? {lat, lng} : null;
  const pickMode = params.get('pick') === '1';

  const setParcelId = useCallback((id) => {
    setParams((p) => {
      const next = new URLSearchParams(p);
      if (id) next.set('parcel', id); else next.delete('parcel');
      return next;
    }, {replace: true});
  }, [setParams]);

  const setPickedLocation = useCallback((loc) => {
    setParams((p) => {
      const next = new URLSearchParams(p);
      if (loc && Number.isFinite(loc.lat) && Number.isFinite(loc.lng)) {
        next.set('lat', String(loc.lat));
        next.set('lng', String(loc.lng));
      } else {
        next.delete('lat');
        next.delete('lng');
      }
      return next;
    }, {replace: true});
  }, [setParams]);

  const setPickMode = useCallback((on) => {
    setParams((p) => {
      const next = new URLSearchParams(p);
      if (on) next.set('pick', '1'); else next.delete('pick');
      return next;
    }, {replace: true});
  }, [setParams]);

  return {
    parcelId, setParcelId,
    pickedLocation, setPickedLocation,
    pickMode, setPickMode,
  };
}
