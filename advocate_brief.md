# Advocate hand-off brief

This brief lists what the uploaded documents show, what they contradict, and what nobody has checked.
It is a document analysis and a question list. It is not a legal opinion and does not say anything
about who owns the property.

## 1. Missing or inconsistent registration details
- **POA registration number missing** (see page 1: "acting through his

duly constituted attorney Anil Sharma under a General Power of Attorne")
  The seller signed through an attorney (power of attorney), but the deed gives no registration number for that power of attorney.
  *Ask for:* The registered power of attorney and its registration number.  
  *Field:* `acting_through_poa.poa_reg_no`

## 2. Points to discuss with your advocate
- **Registry cross-check could not be performed** (see page 2)
  We could not look this property up in the registry index (no usable ULPIN or no match), so no ownership-history comparison was done.
  *Ask for:* An encumbrance certificate and the land revenue / mutation records.  
  *Field:* `property.ulpin`

## 3. Parts we could not read
- **Could not read: property.area_value**
  Part of the document could not be read reliably, so checks depending on it were not run. This says nothing about the deed itself.
  *Ask for:* A clearer copy of the page.  
  *Field:* `property.area_value`

## 4. Documents to request from the seller
- Ask for: The registration number of the power of attorney.
- Ask for: The property's ULPIN (Bhu-Aadhaar) number.
- Upload a clearer copy so we can read: The area of the property.

## 5. What we did not check
- Encumbrance certificate (mortgages, charges)
- Mutation / revenue records
- Court cases or litigation
- Succession or inheritance records not in your upload
- Other deeds not in your upload
- Prohibited-property or acquisition lists
- Physical possession of the property

*A result of "nothing found" means only that nothing was found among the documents you uploaded.*
