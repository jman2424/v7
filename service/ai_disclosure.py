"""Delivery-owned AI identification, independent of model and tenant copy."""

AI_LABEL = 'AI assistant'
WEB_NOTICE = 'Replies may be AI-generated and can contain mistakes.'
MESSAGE_LABEL = 'AI assistant · AI-assisted reply'
EMAIL_NOTICE = 'AI-assisted reply. Please check important details with the business team.'


def message_reply(reply):
    prefix = MESSAGE_LABEL + '\n\n'
    return reply if not reply or reply.startswith(prefix) else prefix + reply


def email_reply(reply):
    footer = '\n\n---\n' + EMAIL_NOTICE
    return reply if reply.endswith(footer) else reply + footer


_PHONE = {
    'en': {
        'automatic': 'You are speaking to an AI assistant using an AI-generated voice. Your words are transcribed and saved for this business. Do not share passwords or payment information.',
        'review': 'This is an AI message-taking service using an AI-generated voice. Your words are transcribed and saved for the team. Do not share passwords or payment information.',
        'question': 'How can we help? Press 0 to leave a message for the team instead.',
        'message': 'Please say your enquiry and how you would like the team to contact you.',
        'retry': 'I did not hear an enquiry. Please say your question, or press 0 to leave a message for the team.',
        'silent': 'No enquiry was received or saved. Please contact the business using its website. Goodbye.',
        'saved': 'Your message has been saved for the team to review. No booking or account change has been made. Thank you.',
        'waiting': 'One moment while the AI assistant checks the business information.',
        'limit': 'The automated service has reached its limit. Please contact the business using its website.',
        'followup': 'Your enquiry has been saved for the team to review. No booking or account change has been made.',
        'end': 'Please contact the team if you need further help.',
    },
    'fr': {
        'automatic': 'Vous parlez à un assistant IA avec une voix générée par intelligence artificielle. Vos paroles sont transcrites et conservées pour cette entreprise. Ne communiquez ni mot de passe ni données de paiement.',
        'review': 'Ce service de messages utilise une IA et une voix générée par intelligence artificielle. Vos paroles sont transcrites et conservées pour l’équipe. Ne communiquez ni mot de passe ni données de paiement.',
        'question': 'Comment pouvons-nous vous aider ? Appuyez sur 0 pour laisser un message à l’équipe.',
        'message': 'Veuillez expliquer votre demande et indiquer comment l’équipe peut vous contacter.',
        'retry': 'Je n’ai pas entendu votre demande. Veuillez parler ou appuyer sur 0 pour laisser un message à l’équipe.',
        'silent': 'Aucune demande n’a été reçue ni enregistrée. Veuillez contacter l’entreprise sur son site. Au revoir.',
        'saved': 'Votre message a été enregistré pour examen par l’équipe. Aucune réservation ni modification de compte n’a été effectuée. Merci.',
        'waiting': 'Un instant, l’assistant IA consulte les informations de l’entreprise.',
        'limit': 'Le service automatisé a atteint sa limite. Veuillez contacter l’entreprise sur son site.',
        'followup': 'Votre demande a été enregistrée pour examen par l’équipe. Aucune réservation ni modification de compte n’a été effectuée.',
        'end': 'Veuillez contacter l’équipe pour toute aide supplémentaire.',
    },
    'es': {
        'automatic': 'Está hablando con un asistente de IA que usa una voz generada por inteligencia artificial. Sus palabras se transcriben y guardan para esta empresa. No comparta contraseñas ni datos de pago.',
        'review': 'Este servicio de mensajes utiliza IA y una voz generada por inteligencia artificial. Sus palabras se transcriben y guardan para el equipo. No comparta contraseñas ni datos de pago.',
        'question': '¿Cómo podemos ayudarle? Pulse 0 para dejar un mensaje al equipo.',
        'message': 'Explique su consulta e indique cómo quiere que el equipo se ponga en contacto con usted.',
        'retry': 'No he oído su consulta. Hable o pulse 0 para dejar un mensaje al equipo.',
        'silent': 'No se ha recibido ni guardado ninguna consulta. Contacte con la empresa a través de su web. Adiós.',
        'saved': 'Su mensaje se ha guardado para que el equipo lo revise. No se ha realizado ninguna reserva ni cambio de cuenta. Gracias.',
        'waiting': 'Un momento, el asistente de IA consulta la información de la empresa.',
        'limit': 'El servicio automatizado ha alcanzado su límite. Contacte con la empresa a través de su web.',
        'followup': 'Su consulta se ha guardado para que el equipo la revise. No se ha realizado ninguna reserva ni cambio de cuenta.',
        'end': 'Contacte con el equipo si necesita más ayuda.',
    },
    'de': {
        'automatic': 'Sie sprechen mit einem KI-Assistenten mit einer KI-generierten Stimme. Ihre Worte werden für dieses Unternehmen transkribiert und gespeichert. Nennen Sie keine Passwörter oder Zahlungsdaten.',
        'review': 'Dieser Nachrichtendienst nutzt KI und eine KI-generierte Stimme. Ihre Worte werden für das Team transkribiert und gespeichert. Nennen Sie keine Passwörter oder Zahlungsdaten.',
        'question': 'Wie können wir helfen? Drücken Sie 0, um dem Team eine Nachricht zu hinterlassen.',
        'message': 'Bitte nennen Sie Ihr Anliegen und wie das Team Sie kontaktieren soll.',
        'retry': 'Ich habe kein Anliegen gehört. Bitte sprechen Sie oder drücken Sie 0 für eine Nachricht an das Team.',
        'silent': 'Es wurde kein Anliegen empfangen oder gespeichert. Bitte kontaktieren Sie das Unternehmen über seine Website. Auf Wiederhören.',
        'saved': 'Ihre Nachricht wurde zur Prüfung durch das Team gespeichert. Es wurde keine Buchung oder Kontoänderung vorgenommen. Vielen Dank.',
        'waiting': 'Einen Moment, der KI-Assistent prüft die Unternehmensinformationen.',
        'limit': 'Der automatisierte Dienst hat sein Limit erreicht. Bitte kontaktieren Sie das Unternehmen über seine Website.',
        'followup': 'Ihr Anliegen wurde zur Prüfung durch das Team gespeichert. Es wurde keine Buchung oder Kontoänderung vorgenommen.',
        'end': 'Bitte kontaktieren Sie das Team, wenn Sie weitere Hilfe benötigen.',
    },
}


def phone_copy(language, key):
    code = language.split('-', 1)[0] if isinstance(language, str) else 'en'
    return _PHONE.get(code, _PHONE['en'])[key]
