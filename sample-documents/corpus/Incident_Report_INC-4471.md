# Incident Report INC-4471

Reported: September 18, 2023

## Summary

The customer portal outage began on September 14, 2023 at 02:10 UTC and lasted 3 hours. Roughly 1,800 shipments had delayed tracking updates during that window.

## Root Cause

The outage was caused by an expired TLS certificate on the tracking API gateway. Automated certificate renewal had been disabled during a migration.

## Remediation

Certificate renewal was re-enabled and an expiry alert was added 30 days before expiry.
