# Energipilot

Kører dit energisystem (batteri, sol, bilopladning) som en app. Den starter altid i **skygge**: den regner og viser,
hvad den ville gøre, men styrer intet. Hver del kan sættes til *Skygge*, *Styrer* eller *Fra* i panelet, og
**Alt i skygge** stopper al styring med ét tryk.

Første gang kopieres apps'enes egne filer (modeller, logs) fra `seed_from`, så den fortsætter med det, de har lært.
Den skriver aldrig i AppDaemons mappe.
