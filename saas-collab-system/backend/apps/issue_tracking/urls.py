from django.urls import path,include
from rest_framework.routers import DefaultRouter
from .views import *
router=DefaultRouter()
router.register('issues',IssueViewSet,basename='tracking-issue')
router.register('grants',GrantViewSet,basename='tracking-grant')
router.register('rules',RuleViewSet,basename='tracking-rule')
urlpatterns=[path('',include(router.urls)),path('candidates/',Candidates.as_view()),path('summary/',Summary.as_view()),path('notifications/',Notifications.as_view()),path('attachments/<int:pk>/download/',Download.as_view())]
