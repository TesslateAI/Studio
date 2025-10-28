import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

export function useReferralTracking() {
  const location = useLocation();

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const ref = params.get('ref');

    if (ref && !sessionStorage.getItem('referral_tracked')) {
      // Track the landing
      axios.post(`${API_URL}/api/track-landing?ref=${ref}`)
        .then(() => {
          // Store in sessionStorage so we don't track multiple times in same session
          sessionStorage.setItem('referral_tracked', 'true');
          // Also store the referrer for use during signup
          sessionStorage.setItem('referrer', ref);
        })
        .catch((error) => {
          console.error('Failed to track referral:', error);
        });
    }
  }, [location]);
}
